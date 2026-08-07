<#
.SYNOPSIS
    Lance le backend FastAPI et le frontend Next.js en local, sans Docker.

.DESCRIPTION
    Remplace `docker-compose up` pour le développement sur Windows. Le script :
      - crée le venv backend/venv s'il manque, et installe requirements.txt
        quand son empreinte a changé depuis la dernière installation ;
      - lance `npm install` quand node_modules manque ou que package-lock.json
        a changé ;
      - vérifie que les ports sont libres ;
      - propage la clé API du backend (.env) vers le frontend, sans quoi toutes
        les requêtes reviendraient en 401 ;
      - démarre les deux serveurs, attend qu'ils répondent, ouvre le navigateur,
        et arrête tout proprement au Ctrl+C.

.PARAMETER Frontend
    Variante de frontend à lancer : frontend (défaut), frontend-harmonized,
    frontend-redesign.

.PARAMETER Install
    Force la réinstallation des dépendances Python et npm.

.PARAMETER Separate
    Ouvre chaque serveur dans sa propre fenêtre PowerShell au lieu de partager
    la console courante. Le script rend alors la main, les fenêtres survivent.

.PARAMETER Force
    Tue le processus qui occupe un port au lieu de s'arrêter.

.EXAMPLE
    .\dev.ps1
    Backend sur http://127.0.0.1:8000, frontend sur http://localhost:3000.

.EXAMPLE
    .\dev.ps1 -Frontend frontend-redesign -FrontendPort 3001

.EXAMPLE
    .\dev.ps1 -BackendOnly -Install
#>
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$Frontend = "frontend",
    [ValidateRange(1, 65535)]
    [int]$BackendPort = 8000,
    [ValidateRange(1, 65535)]
    [int]$FrontendPort = 3000,
    [switch]$Install,
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$Separate,
    [switch]$Force,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------- affichage --

function Write-Step { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Info { param([string]$Message) Write-Host "    $Message" -ForegroundColor DarkGray }
function Write-Ok   { param([string]$Message) Write-Host "  + $Message" -ForegroundColor Green }
function Write-Note { param([string]$Message) Write-Host "  ! $Message" -ForegroundColor Yellow }
function Fail       { param([string]$Message) Write-Host "  x $Message" -ForegroundColor Red; exit 1 }

# ------------------------------------------------------------------ helpers --

# Lecture d'une variable dans un fichier .env, sans dépendre de python-dotenv :
# le frontend a besoin de API_AUTH_KEY avant que le backend ne démarre.
function Get-DotEnvValue {
    param([string]$Path, [string]$Key)

    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    foreach ($line in (Get-Content -LiteralPath $Path)) {
        $trimmed = $line.Trim()
        if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
        $sep = $trimmed.IndexOf("=")
        if ($sep -lt 1) { continue }
        if ($trimmed.Substring(0, $sep).Trim() -ne $Key) { continue }

        $value = $trimmed.Substring($sep + 1).Trim()
        if ($value.Length -ge 2) {
            $quoted = ($value.StartsWith('"') -and $value.EndsWith('"')) -or
                      ($value.StartsWith("'") -and $value.EndsWith("'"))
            if ($quoted) { $value = $value.Substring(1, $value.Length - 2) }
        }
        return $value
    }
    return $null
}

# Empreinte du fichier de dépendances, comparée à celle enregistrée lors de la
# dernière installation réussie : évite de réinstaller à chaque lancement.
function Test-StampCurrent {
    param([string]$SourceFile, [string]$StampFile)

    if (-not (Test-Path -LiteralPath $StampFile)) { return $false }
    if (-not (Test-Path -LiteralPath $SourceFile)) { return $false }
    $current = (Get-FileHash -LiteralPath $SourceFile -Algorithm SHA256).Hash
    return ((Get-Content -LiteralPath $StampFile -Raw).Trim() -eq $current)
}

function Write-Stamp {
    param([string]$SourceFile, [string]$StampFile)

    $hash = (Get-FileHash -LiteralPath $SourceFile -Algorithm SHA256).Hash
    Set-Content -LiteralPath $StampFile -Value $hash -Encoding utf8
}

function Get-PortListener {
    param([int]$Port)

    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
                Select-Object -First 1
    } catch {
        return $null
    }
    if ($null -eq $conn) { return $null }
    try { return (Get-Process -Id $conn.OwningProcess -ErrorAction Stop) } catch { return $null }
}

function Assert-PortFree {
    param([int]$Port, [string]$Label)

    $owner = Get-PortListener -Port $Port
    if ($null -eq $owner) { return }

    if ($Force) {
        Write-Note "Port $Port occupé par $($owner.ProcessName) (PID $($owner.Id)) — arrêt forcé."
        & taskkill.exe /PID $owner.Id /T /F | Out-Null
        Start-Sleep -Milliseconds 800
        if ($null -ne (Get-PortListener -Port $Port)) { Fail "Port $Port toujours occupé." }
        return
    }

    Fail ("Port $Port ($Label) déjà utilisé par $($owner.ProcessName) (PID $($owner.Id)). " +
          "Relancez avec -Force, ou choisissez un autre port.")
}

# Attend qu'une URL réponde. Rend $false si le processus meurt entre-temps :
# inutile d'attendre 90 s un serveur qui a planté à l'import.
function Wait-Endpoint {
    param([string]$Url, [int]$TimeoutSeconds, [System.Diagnostics.Process]$Process)

    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    while ($watch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if ($null -ne $Process -and $Process.HasExited) { return $false }
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ([int]$response.StatusCode -lt 500) { return $true }
        } catch {
            # Serveur pas encore prêt : on réessaie.
        }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

# Un processus tué depuis l'extérieur (taskkill, gestionnaire des tâches) rend
# souvent un ExitCode nul sur l'objet de Start-Process -PassThru : on ne veut
# pas afficher « (code ) ».
function Format-ExitCode {
    param([System.Diagnostics.Process]$Process)

    try {
        $code = $Process.ExitCode
        if ($null -ne $code) { return "code $code" }
    } catch {
        # Code de sortie indisponible.
    }
    return "arrêt externe"
}

$script:Children = New-Object System.Collections.ArrayList

# taskkill /T plutôt que Stop-Process : `next dev` et uvicorn --reload lancent
# des processus enfants que Stop-Process laisserait tourner, port toujours pris.
function Stop-Children {
    foreach ($proc in $script:Children) {
        if ($null -eq $proc) { continue }
        try {
            if (-not $proc.HasExited) {
                & taskkill.exe /PID $proc.Id /T /F 2>$null | Out-Null
            }
        } catch {
            # Processus déjà disparu.
        }
    }
}

# ---------------------------------------------------------------- contrôles --

if ($BackendOnly -and $FrontendOnly) { Fail "-BackendOnly et -FrontendOnly s'excluent." }

$Root = $PSScriptRoot
if (-not $Root) { $Root = (Get-Location).Path }

$RunBackend  = -not $FrontendOnly
$RunFrontend = -not $BackendOnly

$BackendDir  = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root $Frontend

if ($RunBackend -and -not (Test-Path -LiteralPath (Join-Path $BackendDir "run_server.py"))) {
    Fail "backend/run_server.py introuvable. Lancez le script depuis la racine du dépôt."
}

if ($RunFrontend -and -not (Test-Path -LiteralPath (Join-Path $FrontendDir "package.json"))) {
    $available = (Get-ChildItem -LiteralPath $Root -Directory -Filter "frontend*" |
                  Select-Object -ExpandProperty Name) -join ", "
    Fail "Frontend '$Frontend' introuvable. Variantes disponibles : $available"
}

Write-Host ""
Write-Host " No-Code Data Intelligence — lancement local (sans Docker)" -ForegroundColor White
Write-Host ""

# ------------------------------------------------------------------ backend --

$VenvDir    = Join-Path $BackendDir "venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if ($RunBackend) {
    Write-Step "Backend — environnement Python"

    $freshVenv = $false
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        $basePython = $null

        # Le projet est épinglé sur 3.11 (numpy/numba/torch) : on demande cette
        # version au lanceur `py` avant de se rabattre sur le python du PATH.
        if (Get-Command py -ErrorAction SilentlyContinue) {
            try {
                $found = & py -3.11 -c "import sys; print(sys.executable)"
                if ($LASTEXITCODE -eq 0 -and $found) { $basePython = $found.Trim() }
            } catch {
                $basePython = $null
            }
        }
        if (-not $basePython) {
            $cmd = Get-Command python -ErrorAction SilentlyContinue
            if ($cmd) { $basePython = $cmd.Source }
        }
        if (-not $basePython) { Fail "Python introuvable. Installez Python 3.11 puis relancez." }

        Write-Info "Création du venv avec $basePython"
        & $basePython -m venv $VenvDir
        if ($LASTEXITCODE -ne 0) { Fail "Échec de la création du venv." }
        $freshVenv = $true
    }

    $requirements = Join-Path $BackendDir "requirements.txt"
    $pyStamp      = Join-Path $VenvDir ".requirements.sha256"

    $installPython = $Install -or $freshVenv
    if (-not $installPython -and -not (Test-StampCurrent -SourceFile $requirements -StampFile $pyStamp)) {
        # Venv antérieur au script : s'il contient déjà uvicorn, on l'accepte et
        # on pose l'empreinte, plutôt que d'imposer une réinstallation de torch.
        if (Test-Path -LiteralPath (Join-Path $VenvDir "Scripts\uvicorn.exe")) {
            Write-Stamp -SourceFile $requirements -StampFile $pyStamp
            Write-Info "Venv existant réutilisé (utilisez -Install pour réinstaller)."
        } else {
            $installPython = $true
        }
    }

    if ($installPython) {
        Write-Info "pip install -r requirements.txt (long au premier passage)"
        & $VenvPython -m pip install --disable-pip-version-check --quiet --upgrade pip
        & $VenvPython -m pip install --disable-pip-version-check -r $requirements
        if ($LASTEXITCODE -ne 0) { Fail "Échec de l'installation des dépendances Python." }
        Write-Stamp -SourceFile $requirements -StampFile $pyStamp
    }
    Write-Ok "Python prêt : $VenvPython"
}

# ----------------------------------------------------------------- frontend --

$NpmCommand = $null

if ($RunFrontend) {
    Write-Step "Frontend — dépendances npm ($Frontend)"

    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) { $npm = Get-Command npm -ErrorAction SilentlyContinue }
    if (-not $npm) { Fail "npm introuvable. Installez Node.js 18+ puis relancez." }
    $NpmCommand = $npm.Source

    $nodeModules = Join-Path $FrontendDir "node_modules"
    $lockFile    = Join-Path $FrontendDir "package-lock.json"
    $npmStamp    = Join-Path $nodeModules ".sali-install.sha256"

    $installNpm = $Install -or (-not (Test-Path -LiteralPath $nodeModules))
    if (-not $installNpm -and (Test-Path -LiteralPath $lockFile)) {
        if (-not (Test-StampCurrent -SourceFile $lockFile -StampFile $npmStamp)) {
            # node_modules posé par un `npm install` manuel : on pose l'empreinte
            # sans réinstaller, l'arbre est déjà cohérent avec le lock.
            Write-Stamp -SourceFile $lockFile -StampFile $npmStamp
        }
    }

    if ($installNpm) {
        Write-Info "npm install dans $Frontend"
        Push-Location $FrontendDir
        try {
            & $NpmCommand install
            if ($LASTEXITCODE -ne 0) { Fail "Échec de npm install." }
        } finally {
            Pop-Location
        }
        if (Test-Path -LiteralPath $lockFile) { Write-Stamp -SourceFile $lockFile -StampFile $npmStamp }
    }
    Write-Ok "node_modules prêt"
}

# ------------------------------------------------------------------- ports ---

Write-Step "Ports"
if ($RunBackend)  { Assert-PortFree -Port $BackendPort  -Label "backend" }
if ($RunFrontend) { Assert-PortFree -Port $FrontendPort -Label "frontend" }
Write-Ok "Ports libres"

# ------------------------------------------------ variables d'environnement --

Write-Step "Configuration"

$envFile = Join-Path $BackendDir ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    Write-Note "backend/.env absent : créez-le avec GEMINI_API_KEY (voir README)."
} elseif (-not (Get-DotEnvValue -Path $envFile -Key "GEMINI_API_KEY")) {
    Write-Note "GEMINI_API_KEY absente de backend/.env : l'analyse par l'IA échouera."
}

$env:PYTHONUNBUFFERED = "1"
$env:BACKEND_HOST     = "127.0.0.1"
$env:BACKEND_PORT     = "$BackendPort"

$env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:$BackendPort"

# Le backend rejette tout en 401 dès qu'API_AUTH_KEY est définie ; le frontend
# doit envoyer la même valeur dans X-API-Key. Assignation systématique (chaîne
# vide comprise) pour ne pas hériter d'une clé périmée de la session courante.
$apiKey = Get-DotEnvValue -Path $envFile -Key "API_AUTH_KEY"
if ($null -eq $apiKey) { $apiKey = "" }
$env:NEXT_PUBLIC_API_KEY = $apiKey
if ($apiKey -ne "") { Write-Info "Authentification API active (X-API-Key propagée au frontend)." }

# Venv dédié à TimeCopilot, optionnel : sans lui, la prévision bascule sur le
# pipeline interne (voir backend/app/services/timecopilot_service.py).
if (-not $env:TIMECOPILOT_PYTHON) {
    $tcPython = Join-Path $BackendDir ".venv-timecopilot\Scripts\python.exe"
    if (Test-Path -LiteralPath $tcPython) {
        $env:TIMECOPILOT_PYTHON = $tcPython
        Write-Info "TimeCopilot : venv dédié détecté."
    }
}

Write-Ok "Environnement configuré"

# ---------------------------------------------------------------- lancement --

Write-Step "Démarrage"

$backendUrl  = "http://127.0.0.1:$BackendPort"
$frontendUrl = "http://localhost:$FrontendPort"

if ($Separate) {
    if ($RunBackend) {
        Start-Process powershell -ArgumentList @(
            "-NoExit", "-Command",
            "Set-Location '$BackendDir'; & '$VenvPython' run_server.py"
        ) | Out-Null
        Write-Ok "Backend lancé dans une fenêtre séparée — $backendUrl"
    }
    if ($RunFrontend) {
        Start-Process powershell -ArgumentList @(
            "-NoExit", "-Command",
            "Set-Location '$FrontendDir'; & '$NpmCommand' run dev -- --port $FrontendPort"
        ) | Out-Null
        Write-Ok "Frontend lancé dans une fenêtre séparée — $frontendUrl"
    }

    if ($RunFrontend -and -not $NoBrowser) {
        if (Wait-Endpoint -Url $frontendUrl -TimeoutSeconds 120 -Process $null) {
            Start-Process $frontendUrl | Out-Null
        }
    }

    Write-Host ""
    Write-Host " Fermez les fenêtres pour arrêter les serveurs." -ForegroundColor DarkGray
    Write-Host ""
    exit 0
}

$backendProc  = $null
$frontendProc = $null

try {
    if ($RunBackend) {
        $backendProc = Start-Process -FilePath $VenvPython -ArgumentList "run_server.py" `
            -WorkingDirectory $BackendDir -NoNewWindow -PassThru
        [void]$script:Children.Add($backendProc)
        Write-Info "Backend démarré (PID $($backendProc.Id))"
    }

    if ($RunFrontend) {
        $frontendProc = Start-Process -FilePath $NpmCommand `
            -ArgumentList @("run", "dev", "--", "--port", "$FrontendPort") `
            -WorkingDirectory $FrontendDir -NoNewWindow -PassThru
        [void]$script:Children.Add($frontendProc)
        Write-Info "Frontend démarré (PID $($frontendProc.Id))"
    }

    # Le backend importe torch et ydata-profiling : compter en dizaines de
    # secondes au premier démarrage, cache de bytecode froid.
    if ($RunBackend) {
        Write-Info "Attente du backend (import de torch, premier démarrage lent)…"
        if (Wait-Endpoint -Url "$backendUrl/health" -TimeoutSeconds 180 -Process $backendProc) {
            Write-Ok "Backend en ligne — $backendUrl (docs : $backendUrl/docs)"
        } elseif ($backendProc.HasExited) {
            Fail "Le backend s'est arrêté au démarrage (voir la sortie ci-dessus)."
        } else {
            Write-Note "Backend toujours silencieux après 180 s : il continue de démarrer."
        }
    }

    if ($RunFrontend) {
        if (Wait-Endpoint -Url $frontendUrl -TimeoutSeconds 180 -Process $frontendProc) {
            Write-Ok "Frontend en ligne — $frontendUrl"
            if (-not $NoBrowser) { Start-Process $frontendUrl | Out-Null }
        } elseif ($frontendProc.HasExited) {
            Fail "Le frontend s'est arrêté au démarrage (voir la sortie ci-dessus)."
        } else {
            Write-Note "Frontend toujours silencieux après 180 s : il continue de compiler."
        }
    }

    Write-Host ""
    if ($RunBackend -and $RunFrontend) {
        Write-Host " Ctrl+C pour arrêter les deux serveurs." -ForegroundColor DarkGray
    } else {
        Write-Host " Ctrl+C pour arrêter le serveur." -ForegroundColor DarkGray
    }
    Write-Host ""

    while ($true) {
        $backendDown  = ($null -ne $backendProc)  -and $backendProc.HasExited
        $frontendDown = ($null -ne $frontendProc) -and $frontendProc.HasExited
        if ($backendDown)  { Write-Note "Le backend s'est arrêté ($(Format-ExitCode -Process $backendProc))."; break }
        if ($frontendDown) { Write-Note "Le frontend s'est arrêté ($(Format-ExitCode -Process $frontendProc))."; break }
        Start-Sleep -Milliseconds 500
    }
} finally {
    Write-Host ""
    Write-Step "Arrêt des serveurs"
    Stop-Children
    Write-Ok "Terminé"
}
