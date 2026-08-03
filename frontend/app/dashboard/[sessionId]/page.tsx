"use client";

import { useEffect, useState } from "react";
import { toggleTheme, useTheme } from "@/hooks/use-theme";
import { useParams } from "next/navigation";
import { 
  BarChart, Bar, PieChart, Pie, LineChart, Line, XAxis, YAxis, 
  CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell 
} from "recharts";
import { ArrowLeft, ArrowUpDown, Loader2, Table2, BarChart3, Info, Rows3, Columns3, AlertTriangle, Copy, Sun, Moon, Sparkles, Send, MessageCircleQuestion, Search } from "lucide-react";
import { Download } from "@/components/animate-ui/icons/download";
import { API_URL } from "@/lib/api";

// Colors for charts
const COLORS = ['#4E79A7', '#59A14F', '#F28E2B', '#E15759', '#B07AA1', '#76B7B2', '#EDC948', '#FF9DA7', '#9C755F'];

// Formatte les valeurs de l'axe Y de façon compacte (1200 -> "1,2k") pour éviter
// les libellés à rallonge qui se chevauchent, et arrondit le bruit flottant.
const formatAxisNumber = (value: number) =>
  new Intl.NumberFormat("fr-FR", { notation: "compact", maximumFractionDigits: 2 }).format(value);

const formatDecimal = (value: number) =>
  new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 }).format(value);

const formatDisplayValue = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? formatDecimal(value) : String(value);

const formatTooltipValue = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? formatDecimal(value) : String(value ?? "");

// Sur un axe temporel proportionnel, la granularité des libellés doit suivre
// l'amplitude réellement couverte : afficher une date complète sur dix ans est
// illisible, afficher seulement l'année sur une semaine ne dit plus rien.
const formatTimeTick = (ts: number, spanDays: number) => {
  const date = new Date(ts);
  if (spanDays <= 2) return date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  if (spanDays <= 90) return date.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });
  if (spanDays <= 1095) return date.toLocaleDateString("fr-FR", { month: "short", year: "2-digit" });
  return date.getFullYear().toString();
};

interface DashboardData {
  overview: {
    n_lignes?: number;
    n_colonnes?: number;
    pct_valeurs_manquantes_total?: number;
    n_doublons?: number;
  };
  preview: Record<string, unknown>[];
  variables: Record<string, unknown>;
  distributions: Record<string, {
    type: string;
    /** Graphique choisi par le backend : histogram | bar | hbar | donut | line */
    chart?: string;
    /** Lignes exclues du graphique faute de valeur : ce n'est pas une modalité. */
    n_missing?: number;
    pct_missing?: number;
    /** Séries temporelles : granularités disponibles et points par granularité */
    granularities?: { key: string; label: string; points: number }[];
    default_granularity?: string;
    series?: Record<string, { name: string; value: number; ts?: number }[]>;
    data: { name: string; value: number; ts?: number }[];
  }>;
  datasets?: { id: string; name: string; filename?: string; source?: string; rows?: number; columns?: number }[];
  dataset_id?: string;
  filename: string;
}

export default function DashboardPage() {
  const { sessionId } = useParams();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedVar, setSelectedVar] = useState<string>("");
  // Le thème vit dans l'attribut data-theme de <html> : on s'y abonne au lieu de
  // le recopier dans un state depuis un effet (rendu en cascade au montage).
  const theme = useTheme();
  const [selectedDataset, setSelectedDataset] = useState<string>("");
  // Granularité temporelle choisie manuellement ; vide = celle proposée par défaut.
  const [granularity, setGranularity] = useState<string>("");
  // Interprétation textuelle de la variable sélectionnée (générée par le LLM).
  const [interpretation, setInterpretation] = useState<string>("");
  const [interpretLoading, setInterpretLoading] = useState(false);
  const [interpretError, setInterpretError] = useState("");
  const [chartQuestion, setChartQuestion] = useState("");
  const [chartConversation, setChartConversation] = useState<
    { context: string; question: string; answer: string }[]
  >([]);
  const [questionLoading, setQuestionLoading] = useState(false);
  const [questionError, setQuestionError] = useState<{ context: string; text: string } | null>(null);
  const [variableFilter, setVariableFilter] = useState("");
  const [sortConfig, setSortConfig] = useState<{ key: string; direction: "asc" | "desc" } | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const apiUrl = API_URL;
        const query = selectedDataset ? `?dataset_id=${encodeURIComponent(selectedDataset)}` : "";
        const res = await fetch(`${apiUrl}/api/dashboard/data/${sessionId}${query}`);
        if (!res.ok) throw new Error("Erreur lors de la récupération des données");
        const json = await res.json();
        setData(json);

        // Les variables changent d'un dataset à l'autre : on ne conserve la
        // sélection courante que si elle existe encore.
        const vars = Object.keys(json.distributions || {});
        // Un numéro d'ordre est souvent la première colonne du fichier : ouvrir
        // dessus donnait un histogramme plat et sans intérêt en guise de
        // première impression. On ouvre sur une vraie variable d'analyse.
        const analysables = vars.filter(
          (name) => (json.variables?.[name]?.role ?? "analysable") === "analysable"
        );
        const parDefaut = analysables[0] ?? vars[0] ?? "";
        setSelectedVar((current) => (current && vars.includes(current) ? current : parDefaut));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Erreur de récupération");
      } finally {
        setLoading(false);
      }
    };
    if (sessionId) fetchData();
  }, [sessionId, selectedDataset]);

  // Interprétation de la variable sélectionnée : rechargée à chaque changement
  // de variable ou de jeu de données, pour que le texte suive toujours le
  // graphique affiché.
  // Le texte affiché doit être purgé DÈS que la variable change, pas au tour de
  // rendu suivant : sinon l'ancienne interprétation reste sous le nouveau
  // graphique. On ajuste donc l'état pendant le rendu (motif React documenté)
  // plutôt que depuis un effet, qui provoquerait un rendu en cascade.
  const cleInterpretation = `${sessionId ?? ""}|${selectedVar}|${data?.dataset_id ?? ""}`;
  const [cleInterpretationPrec, setCleInterpretationPrec] = useState(cleInterpretation);
  if (cleInterpretation !== cleInterpretationPrec) {
    setCleInterpretationPrec(cleInterpretation);
    setInterpretation("");
    setInterpretError("");
    setInterpretLoading(Boolean(sessionId && selectedVar && data));
    setChartQuestion("");
    setChartConversation([]);
    setQuestionError(null);
    setQuestionLoading(false);
  }

  useEffect(() => {
    if (!sessionId || !selectedVar || !data) {
      return;
    }
    let cancelled = false;

    const apiUrl = API_URL;
    const model = typeof window !== "undefined" ? localStorage.getItem("selected_model") || "" : "";
    const params = new URLSearchParams({ variable: selectedVar });
    if (data.dataset_id) params.set("dataset_id", data.dataset_id);
    if (model) params.set("model", model);

    fetch(`${apiUrl}/api/dashboard/interpret/${sessionId}?${params.toString()}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error("Erreur"))))
      .then((json) => {
        if (!cancelled) setInterpretation(json.interpretation || "");
      })
      .catch(() => {
        if (!cancelled) setInterpretError("Interprétation indisponible pour le moment.");
      })
      .finally(() => {
        if (!cancelled) setInterpretLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, selectedVar, data?.dataset_id]);

  if (loading) return (
    <div className="flex h-screen w-full items-center justify-center bg-gray-50 dark:bg-[#111]">
      <Loader2 className="animate-spin w-8 h-8 text-blue-500" />
      <span className="ml-3 text-lg font-medium text-gray-700 dark:text-gray-300">Chargement du dashboard...</span>
    </div>
  );

  if (error) return (
    <div className="flex h-screen w-full items-center justify-center bg-gray-50 dark:bg-[#111]">
      <div className="bg-red-50 text-red-600 p-6 rounded-xl border border-red-200">
        <h2 className="text-xl font-bold mb-2">Erreur</h2>
        <p>{error}</p>
        <button type="button" onClick={() => window.location.reload()} className="mt-4 rounded-lg bg-red-600 px-4 py-2 font-semibold text-white">Réessayer</button>
      </div>
    </div>
  );

  if (!data) return null;

  const { overview, preview, variables, distributions, filename } = data;
  const activeDist = selectedVar ? distributions[selectedVar] : null;

  // Le backend choisit le graphique adapté à la nature de la colonne. On garde
  // une correspondance de repli pour les sessions analysées avant cette version,
  // dont les distributions ne portent pas encore de champ `chart`.
  const chartKind =
    activeDist?.chart ??
    (activeDist?.type === "categorical"
      ? "donut"
      : activeDist?.type === "numeric"
        ? "histogram"
        : activeDist?.type === "timeseries" || activeDist?.type === "datetime"
          ? "line"
          : null);

  // Séries temporelles : toutes les granularités arrivent dans la même réponse,
  // le changement d'échelle est donc instantané (aucun rechargement).
  const granularityOptions = activeDist?.granularities ?? [];
  const activeGranularity =
    granularity && activeDist?.series?.[granularity]
      ? granularity
      : activeDist?.default_granularity ?? "";
  const chartData =
    (activeGranularity && activeDist?.series?.[activeGranularity]) || activeDist?.data || [];

  const timestamps = chartData
    .map((point) => point.ts)
    .filter((ts): ts is number => typeof ts === "number");
  const hasTimestamps = timestamps.length > 1;
  const spanDays = hasTimestamps
    ? (Math.max(...timestamps) - Math.min(...timestamps)) / 86_400_000
    : 0;

  const datasets = data.datasets ?? [];
  const filteredVariables = Object.keys(variables).filter((name) => name.toLocaleLowerCase("fr").includes(variableFilter.toLocaleLowerCase("fr")));
  // Un numéro d'ordre ou un patronyme désigne une ligne, il ne la caractérise
  // pas : ces colonnes quittent le choix principal pour une section repliée.
  // Elles restent consultables — c'est là qu'on repère un trou dans la
  // numérotation ou un doublon de nom. Le rôle vient du backend
  // (profiling_service.detecter_role).
  const roleDe = (name: string) =>
    (variables[name] as { role?: string } | undefined)?.role ?? "analysable";
  const variablesAnalysables = filteredVariables.filter((name) => roleDe(name) === "analysable");
  const variablesIdentifiants = filteredVariables.filter((name) => roleDe(name) !== "analysable");

  const renderVariable = (varName: string) => {
    const varInfo = variables[varName] as { type?: string; pct_manquantes?: number } | undefined;
    const isSelected = selectedVar === varName;
    return (
      <button
        key={varName}
        onClick={() => setSelectedVar(varName)}
        className={`w-full text-left px-4 py-3 rounded-xl transition-all border ${
          isSelected
            ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800'
            : 'bg-gray-50 dark:bg-[#222] border-transparent hover:border-gray-300 dark:hover:border-gray-700'
        }`}
      >
        <div className="flex justify-between items-center">
          <span className={`font-medium truncate mr-2 ${isSelected ? 'text-blue-700 dark:text-blue-400' : ''}`}>{varName}</span>
          <span className="text-xs px-2 py-1 bg-gray-200 dark:bg-[#333] text-gray-600 dark:text-gray-300 rounded-md shrink-0">
            {varInfo?.type ?? "inconnu"}
          </span>
        </div>
        {(varInfo?.pct_manquantes ?? 0) > 0 && (
          <div className="text-xs text-orange-500 mt-1">
            {varInfo?.pct_manquantes ?? 0}% manquantes
          </div>
        )}
      </button>
    );
  };
  const sortedPreview = sortConfig ? [...preview].sort((a, b) => {
    const left = a[sortConfig.key];
    const right = b[sortConfig.key];
    const comparison = String(left ?? "").localeCompare(String(right ?? ""), "fr", { numeric: true });
    return sortConfig.direction === "asc" ? comparison : -comparison;
  }) : preview;
  const exportPreview = () => {
    const columns = Object.keys(preview[0] || {});
    const escapeCell = (value: unknown) => `"${String(value ?? "").replaceAll('"', '""')}"`;
    const csv = [columns.map(escapeCell).join(","), ...sortedPreview.map((row) => columns.map((column) => escapeCell(row[column])).join(","))].join("\n");
    // BOM en tête, comme l'export des prévisions (TimeSeriesModelView) : Excel
    // ignore le `charset` d'un fichier local et décode avec la page de codes du
    // système. Sans lui, « Réclamation non fondée » s'ouvre en « RÃ©clamation
    // non fondÃ©e » — les octets sont pourtant du bon UTF-8.
    const url = URL.createObjectURL(new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${filename || "donnees"}-apercu.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleChartQuestion = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const question = chartQuestion.trim();
    if (!question || !selectedVar || questionLoading) return;

    setQuestionLoading(true);
    setQuestionError(null);
    const questionContext = cleInterpretation;
    try {
      const model = localStorage.getItem("selected_model") || undefined;
      const res = await fetch(`${API_URL}/api/dashboard/question/${sessionId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          variable: selectedVar,
          question,
          dataset_id: data.dataset_id || undefined,
          model,
        }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || "Impossible de répondre à cette question.");
      setChartConversation((current) => [
        ...current,
        {
          context: questionContext,
          question,
          answer: json.answer || "Aucune réponse disponible.",
        },
      ]);
      setChartQuestion("");
    } catch (err) {
      setQuestionError({
        context: questionContext,
        text: err instanceof Error ? err.message : "Impossible de répondre à cette question.",
      });
    } finally {
      setQuestionLoading(false);
    }
  };

  return (
    <div className="dashboard-shell min-h-screen w-full bg-gray-50 dark:bg-[#111] text-gray-900 dark:text-gray-100 font-sans">
      <div className="dashboard-container">
        
        {/* Header */}
        <div className="dashboard-header flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Dashboard Analytique</h1>
            <p className="text-gray-500 dark:text-gray-400 mt-1 flex items-center gap-2">
              <Table2 className="w-4 h-4" /> Fichier source : <span className="font-semibold text-gray-700 dark:text-gray-300">{filename}</span>
            </p>
          </div>
          <div className="flex gap-2">
            {/* Sélecteur de jeu de données : une session peut en porter
                plusieurs (fichier principal, tableau extrait d'un PDF, fichiers
                ajoutés ensuite). */}
            {datasets.length > 1 && (
              <select
                value={data.dataset_id ?? ""}
                onChange={(event) => setSelectedDataset(event.target.value)}
                className="px-3 py-2 bg-white dark:bg-[#222] border border-gray-200 dark:border-gray-800 rounded-lg shadow-sm text-sm font-medium max-w-[280px]"
                aria-label="Jeu de données"
              >
                {datasets.map((dataset) => (
                  <option key={dataset.id} value={dataset.id}>
                    {dataset.name}
                    {dataset.rows ? ` (${dataset.rows} lignes)` : ""}
                  </option>
                ))}
              </select>
            )}
            <button onClick={toggleTheme} aria-label={theme === "dark" ? "Activer le thème clair" : "Activer le thème sombre"} className="dashboard-icon-action bg-white dark:bg-[#222] border border-gray-200 dark:border-gray-800 rounded-lg shadow-sm hover:bg-gray-50 dark:hover:bg-[#333] transition flex items-center justify-center text-sm font-medium">
              {theme === "dark" ? <Sun className="w-4 h-4 text-gray-400" /> : <Moon className="w-4 h-4 text-gray-500" />}
            </button>
            <button onClick={() => window.close()} className="min-h-11 px-4 py-2 bg-white dark:bg-[#222] border border-gray-200 dark:border-gray-800 rounded-lg shadow-sm hover:bg-gray-50 dark:hover:bg-[#333] transition flex items-center gap-2 text-sm font-medium">
              <ArrowLeft className="w-4 h-4" /> {"Fermer l'onglet"}
            </button>
          </div>
        </div>

        {/* Global Stats Overview */}
        <div className="dashboard-stats grid grid-cols-2 md:grid-cols-4">
          <StatCard title="Lignes" value={overview.n_lignes?.toLocaleString() ?? 0} icon={Rows3} />
          <StatCard title="Colonnes" value={overview.n_colonnes?.toLocaleString() ?? 0} icon={Columns3} />
          <StatCard title="Valeurs manquantes" value={`${formatDecimal(overview.pct_valeurs_manquantes_total ?? 0)} %`} icon={AlertTriangle} />
          <StatCard title="Doublons" value={overview.n_doublons?.toLocaleString() ?? 0} icon={Copy} />
        </div>

        <div className="dashboard-main-grid grid grid-cols-1 lg:grid-cols-3">
          {/* Left Column: Variable Selector */}
          <div className="dashboard-panel dashboard-selector lg:col-span-1 bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-gray-800 rounded-2xl shadow-sm">
            <div className="flex items-center gap-2 mb-4">
              <BarChart3 className="w-5 h-5 text-blue-500" />
              <h2 className="text-xl font-bold">Variables</h2>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">Sélectionnez une variable pour visualiser sa distribution.</p>
            <label className="dashboard-search mb-4">
              <Search className="h-4 w-4" aria-hidden="true" />
              <span className="sr-only">Filtrer les variables</span>
              <input value={variableFilter} onChange={(event) => setVariableFilter(event.target.value)} placeholder="Rechercher une variable" />
            </label>
            
            <div className="dashboard-variable-list space-y-2 overflow-y-auto custom-scrollbar">
              {variablesAnalysables.map(renderVariable)}

              {variablesIdentifiants.length > 0 && (
                <details className="mt-3 rounded-xl border border-gray-200 dark:border-gray-800">
                  <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-gray-600 dark:text-gray-300">
                    Identifiants et noms ({variablesIdentifiants.length})
                  </summary>
                  <div className="space-y-2 px-2 pb-2">
                    <p className="px-2 pb-1 text-xs text-gray-500 dark:text-gray-400">
                      Ces colonnes désignent une ligne (numéro d’ordre, identité) au lieu de la caractériser. Leur distribution n’apprend rien, mais elles restent utiles pour repérer un trou dans la numérotation ou un doublon.
                    </p>
                    {variablesIdentifiants.map(renderVariable)}
                  </div>
                </details>
              )}

              {variablesAnalysables.length === 0 && variablesIdentifiants.length === 0 && (
                <p className="px-1 text-sm text-gray-500 dark:text-gray-400">Aucune variable ne correspond à ce filtre.</p>
              )}
            </div>
          </div>

          {/* Right Column: Chart Display */}
          <div className="dashboard-panel dashboard-chart lg:col-span-2 bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-gray-800 rounded-2xl shadow-sm flex flex-col">
            <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="text-xl font-bold flex items-center gap-2">
                  {activeDist?.type === "timeseries" ? "Évolution temporelle de" : "Distribution de"} <span className="text-blue-500">{selectedVar}</span>
                </h2>
                {activeDist && (
                  <span
                    className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                      (activeDist.pct_missing ?? 0) > 0
                        ? "bg-orange-50 text-orange-700 dark:bg-orange-950/30 dark:text-orange-300"
                        : "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400"
                    }`}
                    title={`${(activeDist.n_missing ?? 0).toLocaleString("fr-FR")} valeur${(activeDist.n_missing ?? 0) > 1 ? "s" : ""} manquante${(activeDist.n_missing ?? 0) > 1 ? "s" : ""}, exclue${(activeDist.n_missing ?? 0) > 1 ? "s" : ""} du graphique`}
                  >
                    Valeurs manquantes : {formatDecimal(activeDist.pct_missing ?? 0)} %
                  </span>
                )}
              </div>

              {/* Choix de l'échelle temporelle : toutes les granularités sont
                  déjà chargées, la bascule est donc immédiate. */}
              {granularityOptions.length > 1 && (
                <div className="flex items-center gap-1 rounded-lg border border-gray-200 dark:border-gray-800 p-1">
                  {granularityOptions.map((option) => (
                    <button
                      key={option.key}
                      onClick={() => setGranularity(option.key)}
                      className={`px-3 py-1 rounded-md text-sm font-medium transition ${
                        activeGranularity === option.key
                          ? "bg-blue-500 text-white"
                          : "text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-[#222]"
                      }`}
                      title={`${option.points} points`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="dashboard-chart-canvas flex-1 w-full">
              {!activeDist || chartData.length === 0 ? (
                <div className="h-full flex items-center justify-center text-gray-400">
                  <div className="text-center">
                    <Info className="w-8 h-8 mx-auto mb-2 opacity-50" />
                    <p>Aucune donnée à visualiser pour cette variable.</p>
                  </div>
                </div>
              ) : chartKind === "donut" ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={chartData}
                      cx="38%"
                      cy="50%"
                      innerRadius={72}
                      outerRadius={126}
                      paddingAngle={2}
                      dataKey="value"
                      label={false}
                    >
                      {chartData.map((entry: Record<string, unknown>, index: number) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      formatter={formatTooltipValue}
                      contentStyle={{ borderRadius: '12px', border: '1px solid #333', background: 'rgba(20,20,20,0.9)', color: '#fff' }}
                      itemStyle={{ color: '#fff' }}
                    />
                    <Legend layout="vertical" verticalAlign="middle" align="right" wrapperStyle={{ right: 16, lineHeight: '24px' }} />
                  </PieChart>
                </ResponsiveContainer>
              ) : chartKind === "hbar" ? (
                /* Barres horizontales : les libellés de catégories restent lisibles
                   même longs et nombreux, là où un camembert devient illisible. */
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={chartData}
                    layout="vertical"
                    margin={{ top: 10, right: 30, left: 10, bottom: 10 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" opacity={0.2} horizontal={false} />
                    <XAxis type="number" tick={{fill: '#888', fontSize: 12}} allowDecimals={false} tickFormatter={formatAxisNumber} />
                    <YAxis
                      type="category"
                      dataKey="name"
                      tick={{fill: '#888', fontSize: 12}}
                      width={150}
                      interval={0}
                    />
                    <Tooltip
                      formatter={formatTooltipValue}
                      contentStyle={{ borderRadius: '12px', border: '1px solid #333', background: 'rgba(20,20,20,0.9)', color: '#fff' }}
                      itemStyle={{ color: '#fff' }}
                      cursor={{fill: 'rgba(255,255,255,0.1)'}}
                    />
                    <Bar dataKey="value" fill="#3b82f6" radius={[0, 4, 4, 0]}>
                      {chartData.map((entry: Record<string, unknown>, index: number) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : chartKind === "histogram" || chartKind === "bar" ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 20, right: 30, left: 0, bottom: 50 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                    {/* Pas de interval={0} : Recharts espace les libellés au lieu
                        de tous les forcer, ce qui évite le chevauchement. */}
                    <XAxis
                      dataKey="name"
                      angle={-45}
                      textAnchor="end"
                      height={80}
                      tick={{fill: '#888', fontSize: 12}}
                      minTickGap={4}
                    />
                    <YAxis
                      tick={{fill: '#888'}}
                      domain={[0, 'auto']}
                      allowDecimals={false}
                      tickFormatter={formatAxisNumber}
                      width={56}
                    />
                    <Tooltip
                      formatter={formatTooltipValue}
                      contentStyle={{ borderRadius: '12px', border: '1px solid #333', background: 'rgba(20,20,20,0.9)', color: '#fff' }}
                      itemStyle={{ color: '#fff' }}
                      cursor={{fill: 'rgba(255,255,255,0.1)'}}
                    />
                    <Bar dataKey="value" fill="#3b82f6" radius={[4, 4, 0, 0]}>
                      {chartData.map((entry: Record<string, unknown>, index: number) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : chartKind === "line" ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData} margin={{ top: 20, right: 30, left: 0, bottom: 50 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                    {/* Axe temporel proportionnel quand le backend fournit des
                        horodatages : un trou de trois ans occupe alors vraiment
                        trois ans, au lieu d'un simple cran de plus. */}
                    {hasTimestamps ? (
                      <XAxis
                        dataKey="ts"
                        type="number"
                        scale="time"
                        domain={['dataMin', 'dataMax']}
                        tick={{fill: '#888', fontSize: 12}}
                        tickFormatter={(ts: number) => formatTimeTick(ts, spanDays)}
                        minTickGap={30}
                        height={50}
                      />
                    ) : (
                      <XAxis dataKey="name" angle={-45} textAnchor="end" height={80} tick={{fill: '#888', fontSize: 12}} minTickGap={20} />
                    )}
                    <YAxis
                      tick={{fill: '#888'}}
                      domain={['auto', 'auto']}
                      tickFormatter={formatAxisNumber}
                      width={56}
                    />
                    <Tooltip
                      formatter={formatTooltipValue}
                      contentStyle={{ borderRadius: '12px', border: '1px solid #333', background: 'rgba(20,20,20,0.9)', color: '#fff' }}
                      labelFormatter={(label: React.ReactNode) =>
                        hasTimestamps && (typeof label === "number" || typeof label === "string")
                          ? new Date(Number(label)).toLocaleDateString("fr-FR")
                          : String(label ?? "")
                      }
                    />
                    <Line type="monotone" dataKey="value" stroke="#3b82f6" strokeWidth={3} dot={false} activeDot={{ r: 4, fill: '#3b82f6' }} />
                  </LineChart>
                </ResponsiveContainer>
              ) : null}
            </div>

            {/* Analyse & interprétation de la variable — change avec la sélection */}
            <div className="dashboard-interpretation mt-6 border-t border-gray-100 dark:border-gray-800 pt-5">
              <div className="flex items-center gap-2 mb-3">
                <Sparkles className="w-4 h-4 text-blue-500" />
                <h3 className="text-sm font-bold uppercase tracking-wide text-gray-600 dark:text-gray-300">
                  Analyse & interprétation
                </h3>
              </div>
              {interpretLoading ? (
                <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400 text-sm">
                  <Loader2 className="w-4 h-4 animate-spin" /> Génération de l&apos;interprétation…
                </div>
              ) : interpretError ? (
                <p className="text-sm text-gray-400 italic">{interpretError}</p>
              ) : interpretation ? (
                <p className="text-sm leading-relaxed text-gray-700 dark:text-gray-300 whitespace-pre-line">
                  {interpretation}
                </p>
              ) : (
                <p className="text-sm text-gray-400 italic">
                  Sélectionnez une variable pour afficher son interprétation.
                </p>
              )}

              <div className="mt-8 rounded-2xl border border-blue-100 bg-blue-50/40 p-5 dark:border-blue-900/50 dark:bg-blue-950/20 sm:p-6">
                <div className="mb-5 flex items-center gap-2">
                  <MessageCircleQuestion className="h-4 w-4 text-blue-500" />
                  <p className="text-sm font-semibold text-gray-700 dark:text-gray-200">
                    Une question sur ce graphique ?
                  </p>
                </div>

                <div className="space-y-4" aria-live="polite">
                  {chartConversation
                    .filter((exchange) => exchange.context === cleInterpretation)
                    .map((exchange, index) => (
                      <div key={`${exchange.context}-${index}`} className="space-y-2">
                        <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-blue-500 px-4 py-3 text-sm leading-relaxed text-white">
                          {exchange.question}
                        </div>
                        <div className="max-w-[92%] rounded-2xl rounded-bl-md bg-white px-4 py-3 text-sm leading-relaxed text-gray-700 shadow-sm dark:bg-[#202020] dark:text-gray-300">
                          {exchange.answer}
                        </div>
                      </div>
                    ))}
                  {questionError?.context === cleInterpretation && (
                    <p className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 dark:bg-red-950/20 dark:text-red-400">
                      {questionError.text}
                    </p>
                  )}
                </div>

                <form onSubmit={handleChartQuestion} className="mt-8 flex flex-col items-stretch gap-3 sm:flex-row sm:items-center">
                  <label htmlFor="chart-question" className="sr-only">Question sur le graphique</label>
                  <input
                    type="text"
                    id="chart-question"
                    value={chartQuestion}
                    onChange={(event) => setChartQuestion(event.target.value)}
                    placeholder={`Ex. : Que signifie cette distribution pour « ${selectedVar} » ?`}
                    maxLength={1000}
                    disabled={!selectedVar || questionLoading}
                    className="h-10 min-w-0 flex-1 rounded-lg border border-gray-200 bg-white px-3.5 text-sm leading-5 outline-none transition placeholder:text-gray-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-gray-700 dark:bg-[#181818] dark:focus:border-blue-600 dark:focus:ring-blue-950"
                  />
                  <button
                    type="submit"
                    disabled={!chartQuestion.trim() || !selectedVar || questionLoading}
                    className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-blue-500 px-4 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {questionLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                    {questionLoading ? "Analyse…" : "Demander"}
                  </button>
                </form>
              </div>
            </div>
          </div>
        </div>

        {/* Data Preview Table */}
        <div className="dashboard-panel dashboard-preview bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-gray-800 rounded-2xl shadow-sm overflow-hidden">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-xl font-bold">Aperçu des données ({preview.length} premières lignes)</h2>
            <button type="button" onClick={exportPreview} className="dashboard-secondary-action"><Download animateOnHover className="h-4 w-4" /> Exporter CSV</button>
          </div>
          <div className="overflow-x-auto custom-scrollbar pb-4">
            <table className="w-full text-sm text-left">
              <thead className="text-xs uppercase bg-gray-50 dark:bg-[#222] text-gray-600 dark:text-gray-300">
                <tr>
                  {Object.keys(preview[0] || {}).map(key => (
                    <th key={key} className="sticky top-0 px-6 py-4 font-semibold whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-2" onClick={() => setSortConfig((current) => ({ key, direction: current?.key === key && current.direction === "asc" ? "desc" : "asc" }))}>
                        {key}<ArrowUpDown className="h-3.5 w-3.5" aria-hidden="true" />
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {sortedPreview.map((row: Record<string, unknown>, i: number) => (
                  <tr key={i} className="hover:bg-gray-50/50 dark:hover:bg-white/5 transition">
                    {Object.values(row).map((val: unknown, j: number) => (
                      <td key={j} className="px-6 py-4 whitespace-nowrap text-gray-700 dark:text-gray-400">
                        {val === null ? <span className="text-gray-400 italic">null</span> : formatDisplayValue(val)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

      </div>

      <style dangerouslySetInnerHTML={{__html: `
        .dashboard-shell {
          padding: 32px clamp(20px, 4vw, 72px) 48px;
        }
        .dashboard-container {
          width: min(100%, 1680px);
          margin: 0 auto;
          display: grid;
          gap: 24px;
        }
        .dashboard-header { gap: 24px; }
        .dashboard-stats { gap: 16px; }
        .dashboard-main-grid { gap: 24px; align-items: stretch; }
        .dashboard-panel { padding: 24px; }
        .dashboard-selector, .dashboard-chart { min-height: 500px; }
        .dashboard-selector { display: flex; flex-direction: column; }
        .dashboard-variable-list { flex: 1; max-height: 410px; padding-right: 8px; }
        .dashboard-chart-canvas { min-height: 420px; }
        .dashboard-preview { padding-bottom: 8px; }
        .dashboard-preview > h2 { margin-bottom: 18px; }
        .dashboard-preview td, .dashboard-preview th { padding: 12px 16px; }
        .dashboard-stat { min-height: 104px; padding: 20px; }
        @media (max-width: 1023px) {
          .dashboard-selector, .dashboard-chart { min-height: 440px; }
        }
        @media (max-width: 640px) {
          .dashboard-shell { padding: 20px 14px 32px; }
          .dashboard-container { gap: 16px; }
          .dashboard-header { align-items: flex-start; flex-direction: column; gap: 16px; }
          .dashboard-header > div:last-child { width: 100%; }
          .dashboard-header button:last-child { flex: 1; justify-content: center; }
          .dashboard-stats { gap: 10px; }
          .dashboard-main-grid { gap: 16px; }
          .dashboard-panel { padding: 18px; }
          .dashboard-chart-canvas { min-height: 360px; }
          .dashboard-chart .recharts-legend-wrapper { font-size: 11px; }
        }
        .custom-scrollbar::-webkit-scrollbar {
          height: 6px;
          width: 6px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background-color: rgba(150, 150, 150, 0.3);
          border-radius: 10px;
        }
      `}} />
    </div>
  );
}

function StatCard({ title, value, icon: Icon }: { title: string, value: string | number, icon: React.ComponentType<{ className?: string }> }) {
  return (
    <div className="dashboard-stat bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-gray-800 rounded-2xl shadow-sm flex items-start gap-4">
      <div className="bg-gray-50 dark:bg-[#222] p-3 rounded-xl text-blue-500"><Icon className="w-6 h-6" /></div>
      <div>
        <p className="text-sm text-gray-500 dark:text-gray-400 font-medium">{title}</p>
        <p className="text-2xl font-bold mt-1">{value}</p>
      </div>
    </div>
  );
}
