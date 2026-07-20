"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { 
  BarChart, Bar, PieChart, Pie, LineChart, Line, XAxis, YAxis, 
  CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell 
} from "recharts";
import { ArrowLeft, Loader2, Table2, BarChart3, Info, Rows3, Columns3, AlertTriangle, Copy, Sun, Moon } from "lucide-react";

// Colors for charts
const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884d8', '#82ca9d', '#ffc658', '#d0ed57', '#a4de6c'];

// Formatte les valeurs de l'axe Y de façon compacte (1200 -> "1,2k") pour éviter
// les libellés à rallonge qui se chevauchent, et arrondit le bruit flottant.
const formatAxisNumber = (value: number) =>
  new Intl.NumberFormat("fr-FR", { notation: "compact", maximumFractionDigits: 1 }).format(value);

interface DashboardData {
  overview: {
    n_lignes?: number;
    n_colonnes?: number;
    pct_valeurs_manquantes_total?: number;
    n_doublons?: number;
  };
  preview: Record<string, unknown>[];
  variables: Record<string, unknown>;
  distributions: Record<string, { type: string; data: { name: string; value: number }[] }>;
  filename: string;
}

export default function DashboardPage() {
  const { sessionId } = useParams();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedVar, setSelectedVar] = useState<string>("");
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.attributeName === "data-theme") {
          const newTheme = document.documentElement.getAttribute("data-theme") as "dark" | "light";
          if (newTheme) setTheme(newTheme);
        }
      });
    });
    observer.observe(document.documentElement, { attributes: true });
    
    const currentTheme = document.documentElement.getAttribute("data-theme") as "dark" | "light" | null;
    if (currentTheme) {
      setTheme(currentTheme);
    } else {
      setTheme("dark");
    }
    
    return () => observer.disconnect();
  }, []);

  const toggleTheme = () => {
    const newTheme = theme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", newTheme);
    setTheme(newTheme);
  };

  useEffect(() => {
    const fetchData = async () => {
      try {
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
        const res = await fetch(`${apiUrl}/api/dashboard/data/${sessionId}`);
        if (!res.ok) throw new Error("Erreur lors de la récupération des données");
        const json = await res.json();
        setData(json);
        
        // Select first variable by default if distributions exist
        const vars = Object.keys(json.distributions || {});
        if (vars.length > 0) {
          setSelectedVar(vars[0]);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Erreur de récupération");
      } finally {
        setLoading(false);
      }
    };
    if (sessionId) fetchData();
  }, [sessionId]);

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
      </div>
    </div>
  );

  if (!data) return null;

  const { overview, preview, variables, distributions, filename } = data;
  const activeDist = selectedVar ? distributions[selectedVar] : null;

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
            <button onClick={toggleTheme} className="p-2 bg-white dark:bg-[#222] border border-gray-200 dark:border-gray-800 rounded-lg shadow-sm hover:bg-gray-50 dark:hover:bg-[#333] transition flex items-center justify-center text-sm font-medium">
              {theme === "dark" ? <Sun className="w-4 h-4 text-gray-400" /> : <Moon className="w-4 h-4 text-gray-500" />}
            </button>
            <button onClick={() => window.close()} className="px-4 py-2 bg-white dark:bg-[#222] border border-gray-200 dark:border-gray-800 rounded-lg shadow-sm hover:bg-gray-50 dark:hover:bg-[#333] transition flex items-center gap-2 text-sm font-medium">
              <ArrowLeft className="w-4 h-4" /> {"Fermer l'onglet"}
            </button>
          </div>
        </div>

        {/* Global Stats Overview */}
        <div className="dashboard-stats grid grid-cols-2 md:grid-cols-4">
          <StatCard title="Lignes" value={overview.n_lignes?.toLocaleString() ?? 0} icon={Rows3} />
          <StatCard title="Colonnes" value={overview.n_colonnes?.toLocaleString() ?? 0} icon={Columns3} />
          <StatCard title="Valeurs manquantes" value={`${overview.pct_valeurs_manquantes_total ?? 0}%`} icon={AlertTriangle} />
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
            
            <div className="dashboard-variable-list space-y-2 overflow-y-auto custom-scrollbar">
              {Object.keys(variables).map((varName) => {
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
                )
              })}
            </div>
          </div>

          {/* Right Column: Chart Display */}
          <div className="dashboard-panel dashboard-chart lg:col-span-2 bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-gray-800 rounded-2xl shadow-sm flex flex-col">
            <h2 className="text-xl font-bold mb-6 flex items-center gap-2">
              {activeDist?.type === "timeseries" ? "Évolution temporelle de" : "Distribution de"} <span className="text-blue-500">{selectedVar}</span>
            </h2>
            
            <div className="dashboard-chart-canvas flex-1 w-full">
              {!activeDist || !activeDist.data || activeDist.data.length === 0 ? (
                <div className="h-full flex items-center justify-center text-gray-400">
                  <div className="text-center">
                    <Info className="w-8 h-8 mx-auto mb-2 opacity-50" />
                    <p>Aucune donnée à visualiser pour cette variable.</p>
                  </div>
                </div>
              ) : activeDist.type === "categorical" ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={activeDist.data}
                      cx="38%"
                      cy="50%"
                      innerRadius={72}
                      outerRadius={126}
                      paddingAngle={2}
                      dataKey="value"
                      label={false}
                    >
                      {activeDist.data.map((entry: Record<string, unknown>, index: number) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip 
                      contentStyle={{ borderRadius: '12px', border: '1px solid #333', background: 'rgba(20,20,20,0.9)', color: '#fff' }}
                      itemStyle={{ color: '#fff' }}
                    />
                    <Legend layout="vertical" verticalAlign="middle" align="right" wrapperStyle={{ right: 16, lineHeight: '24px' }} />
                  </PieChart>
                </ResponsiveContainer>
              ) : activeDist.type === "numeric" ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={activeDist.data} margin={{ top: 20, right: 30, left: 0, bottom: 50 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                    <XAxis dataKey="name" angle={-45} textAnchor="end" height={80} tick={{fill: '#888', fontSize: 12}} interval={0} />
                    <YAxis
                      tick={{fill: '#888'}}
                      domain={[0, 'auto']}
                      allowDecimals={false}
                      tickFormatter={formatAxisNumber}
                      width={56}
                    />
                    <Tooltip
                      contentStyle={{ borderRadius: '12px', border: '1px solid #333', background: 'rgba(20,20,20,0.9)', color: '#fff' }}
                      itemStyle={{ color: '#fff' }}
                      cursor={{fill: 'rgba(255,255,255,0.1)'}}
                    />
                    <Bar dataKey="value" fill="#3b82f6" radius={[4, 4, 0, 0]}>
                      {activeDist.data.map((entry: Record<string, unknown>, index: number) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : activeDist.type === "datetime" || activeDist.type === "timeseries" ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={activeDist.data} margin={{ top: 20, right: 30, left: 0, bottom: 50 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                    <XAxis dataKey="name" angle={-45} textAnchor="end" height={80} tick={{fill: '#888', fontSize: 12}} minTickGap={20} />
                    <YAxis
                      tick={{fill: '#888'}}
                      domain={[0, 'auto']}
                      allowDecimals={activeDist.type === "timeseries"}
                      tickFormatter={formatAxisNumber}
                      width={56}
                    />
                    <Tooltip
                      contentStyle={{ borderRadius: '12px', border: '1px solid #333', background: 'rgba(20,20,20,0.9)', color: '#fff' }}
                    />
                    <Line type="monotone" dataKey="value" stroke="#3b82f6" strokeWidth={3} dot={{r: 4, fill: '#3b82f6'}} />
                  </LineChart>
                </ResponsiveContainer>
              ) : null}
            </div>
          </div>
        </div>

        {/* Data Preview Table */}
        <div className="dashboard-panel dashboard-preview bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-gray-800 rounded-2xl shadow-sm overflow-hidden">
          <h2 className="text-xl font-bold mb-4">Aperçu des données (5 premières lignes)</h2>
          <div className="overflow-x-auto custom-scrollbar pb-4">
            <table className="w-full text-sm text-left">
              <thead className="text-xs uppercase bg-gray-50 dark:bg-[#222] text-gray-600 dark:text-gray-300">
                <tr>
                  {Object.keys(preview[0] || {}).map(key => (
                    <th key={key} className="px-6 py-4 font-semibold whitespace-nowrap">{key}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {preview.map((row: Record<string, unknown>, i: number) => (
                  <tr key={i} className="hover:bg-gray-50/50 dark:hover:bg-white/5 transition">
                    {Object.values(row).map((val: unknown, j: number) => (
                      <td key={j} className="px-6 py-4 whitespace-nowrap text-gray-700 dark:text-gray-400">
                        {val === null ? <span className="text-gray-400 italic">null</span> : String(val)}
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
          .dashboard-chart .recharts-legend-wrapper { display: none; }
          .dashboard-chart .recharts-pie { transform: translateX(18%); }
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
