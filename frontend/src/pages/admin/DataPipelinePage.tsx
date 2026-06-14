import type React from "react";
import { useState, useEffect, useRef } from "react";
import {
  Play,
  Square,
  RefreshCw,
  Database,
  Terminal as TerminalIcon,
  Settings,
  Plus,
  X,
  Copy,
  Check,
  Zap,
  HardDrive,
  Calendar,
  Search,
} from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/apiClient";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { Progress } from "@/components/ui/progress";

interface StorageSymbol {
  symbol: string;
  timeframes: string[];
  klines_1m: {
    start_date: string;
    end_date: string;
    size_mb: number;
    is_enriched: boolean;
  } | null;
  has_aggtrades: boolean;
  has_klines_1s: boolean;
  has_oi: boolean;
  has_depth: boolean;
}

const DataPipelinePage: React.FC = () => {
  // Config state
  const [symbols, setSymbols] = useState<string[]>(["BTCUSDT"]);
  const [customSymbol, setCustomSymbol] = useState("");
  const [dataTypes, setDataTypes] = useState<string[]>(["klines", "aggTrades"]);
  const [timeframes, setTimeframes] = useState<string[]>(["1m"]);
  const [startDate, setStartDate] = useState("2024-01-01");
  const [endDate, setEndDate] = useState(new Date().toISOString().split("T")[0]);
  const [updateOnly, setUpdateOnly] = useState(false);
  const [enrichOnly, setEnrichOnly] = useState(false);
  const [deleteAggtrades, setDeleteAggtrades] = useState(true);

  // System state
  const [isRunning, setIsRunning] = useState(false);
  const [logs, setLogs] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [storageData, setStorageData] = useState<StorageSymbol[]>([]);
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState("config");
  const [catchUpDeleteAggtrades, setCatchUpDeleteAggtrades] = useState(true);
  const [progress, setProgress] = useState(0);
  const [currentTask, setCurrentTask] = useState("");

  const terminalEndRef = useRef<HTMLDivElement>(null);

  const fetchStatus = async () => {
    try {
      const data = await apiClient<{ 
        is_running: boolean; 
        logs: string;
        progress: number;
        current_task: string;
      }>("/admin/data-pipeline/status");
      
      setIsRunning(data.is_running);
      setLogs(data.logs);
      setProgress(data.progress);
      setCurrentTask(data.current_task);
    } catch (error) {
      console.error("Error fetching pipeline status:", error);
    }
  };

  const fetchStorageInfo = async () => {
    try {
      const data = await apiClient<{ symbols: StorageSymbol[] }>(
        "/admin/data-pipeline/storage-info"
      );
      setStorageData(data.symbols);
    } catch (error) {
      console.error("Error fetching storage info:", error);
    }
  };

  useEffect(() => {
    fetchStatus();
    fetchStorageInfo();
    const interval = setInterval(() => {
      fetchStatus();
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  const handleStart = async () => {
    try {
      setIsLoading(true);
      await apiClient("/admin/data-pipeline/start", {
        method: "POST",
        body: JSON.stringify({
          symbols: symbols.join(","),
          data_types: dataTypes.join(","),
          timeframes: timeframes.join(","),
          start_date: startDate,
          end_date: endDate,
          update_only: updateOnly,
          enrich_only: enrichOnly,
          delete_aggtrades: deleteAggtrades,
        }),
      });
      toast.success("Pipeline started");
      setIsRunning(true);
      setActiveTab("terminal");
    } catch (error: any) {
      toast.error(error.message || "Failed to start pipeline");
    } finally {
      setIsLoading(false);
    }
  };

  const handleStop = async () => {
    try {
      setIsLoading(true);
      await apiClient("/admin/data-pipeline/stop", { method: "POST" });
      toast.success("Pipeline stopped");
      setIsRunning(false);
    } catch (error: any) {
      toast.error(error.message || "Failed to stop pipeline");
    } finally {
      setIsLoading(false);
    }
  };

  const handleCatchUp = async () => {
    try {
      setIsLoading(true);
      const res: any = await apiClient("/admin/data-pipeline/catch-up", { 
        method: "POST",
        body: JSON.stringify({ delete_aggtrades: catchUpDeleteAggtrades })
      });
      if (res.message) {
         toast.info(res.message);
      } else {
         toast.success("Catch-up process started");
         setIsRunning(true);
         setActiveTab("terminal");
      }
    } catch (error: any) {
      toast.error(error.message || "Failed to start catch-up");
    } finally {
      setIsLoading(false);
    }
  };

  const addCustomSymbol = (e: React.FormEvent) => {
    e.preventDefault();
    const sym = customSymbol.trim().toUpperCase();
    if (sym && !symbols.includes(sym)) {
      setSymbols([...symbols, sym]);
      setCustomSymbol("");
    }
  };

  const toggleSelection = (item: string, list: string[], setList: (l: string[]) => void) => {
    if (list.includes(item)) {
      setList(list.filter((i) => i !== item));
    } else {
      setList([...list, item]);
    }
  };

  const generateCommand = () => {
    let cmd = `python scripts/download_pipeline.py --symbols "${symbols.join(",")}" --data-types "${dataTypes.join(",")}"`;
    if (dataTypes.includes("klines")) cmd += ` --timeframes "${timeframes.join(",")}"`;
    if (updateOnly) cmd += " --update";
    else cmd += ` --start-date ${startDate} --end-date ${endDate}`;
    if (enrichOnly) cmd += " --enrich-only";
    if (deleteAggtrades) cmd += " --delete-aggtrades";
    return cmd;
  };

  const handleCopyCommand = () => {
    navigator.clipboard.writeText(generateCommand());
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    toast.success("Command copied to clipboard");
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Data Pipeline Manager</h1>
          <p className="text-muted-foreground">
            Manage Binance historical data downloading and enrichment.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isRunning ? (
            <Badge className="bg-green-500 hover:bg-green-600">
              <RefreshCw className="mr-1 h-3 w-3 animate-spin" />
              Running
            </Badge>
          ) : (
            <Badge variant="outline" className="text-muted-foreground">
              Idle
            </Badge>
          )}
        </div>
      </div>

      {isRunning && (
        <Card className="border-primary/20 bg-primary/5">
          <CardContent className="p-4 space-y-2">
            <div className="flex justify-between items-end">
              <div className="space-y-1">
                <span className="text-[10px] text-muted-foreground uppercase font-bold tracking-wider">Current Activity</span>
                <p className="text-sm font-medium">{currentTask || (isRunning ? "Initializing pipeline..." : "Pipeline finished")}</p>
              </div>
              <span className="text-2xl font-mono font-bold text-primary">{Math.round(progress)}%</span>
            </div>
            <Progress value={progress} className="h-2" />
          </CardContent>
        </Card>
      )}

      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="grid w-full grid-cols-3 lg:w-[400px]">
          <TabsTrigger value="config" className="flex items-center gap-2">
            <Settings className="h-4 w-4" /> Config
          </TabsTrigger>
          <TabsTrigger value="storage" className="flex items-center gap-2">
            <Database className="h-4 w-4" /> Storage
          </TabsTrigger>
          <TabsTrigger value="terminal" className="flex items-center gap-2">
            <TerminalIcon className="h-4 w-4" /> Logs
          </TabsTrigger>
        </TabsList>

        <TabsContent value="config" className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Pipeline Configuration</CardTitle>
                <CardDescription>Configure parameters for Binance ETL process.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                {/* Symbols */}
                <div className="space-y-3">
                  <Label>1. Symbols (USDT-M Futures)</Label>
                  <div className="flex flex-wrap gap-2 p-3 bg-muted/30 rounded-lg border">
                    {symbols.map((sym) => (
                      <Badge key={sym} variant="secondary" className="flex items-center gap-1 pl-2 pr-1 py-1">
                        {sym}
                        <button onClick={() => setSymbols(symbols.filter(s => s !== sym))} className="hover:text-destructive">
                          <X className="h-3 w-3" />
                        </button>
                      </Badge>
                    ))}
                    <form onSubmit={addCustomSymbol} className="inline-flex items-center">
                      <Input
                        className="h-7 w-32 text-xs"
                        placeholder="Add symbol..."
                        value={customSymbol}
                        onChange={(e) => setCustomSymbol(e.target.value)}
                      />
                      <Button size="icon" variant="ghost" className="h-7 w-7 ml-1">
                        <Plus className="h-4 w-4" />
                      </Button>
                    </form>
                  </div>
                </div>

                {/* Data Types */}
                <div className="space-y-3">
                  <Label>2. Data Types</Label>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {[
                      { id: "klines", label: "Klines (Candlesticks)", desc: "OHLCV historical data" },
                      { id: "aggTrades", label: "Aggregated Trades", desc: "Tick-by-tick buyer/seller data" },
                      { id: "open_interest", label: "Open Interest", desc: "Open positions metrics" },
                      { id: "bookDepth", label: "Order Book Depth", desc: "Limit order levels" },
                    ].map((type) => (
                      <div
                        key={type.id}
                        onClick={() => toggleSelection(type.id, dataTypes, setDataTypes)}
                        className={`p-3 rounded-lg border cursor-pointer transition-all ${
                          dataTypes.includes(type.id)
                            ? "bg-primary/5 border-primary shadow-sm"
                            : "bg-background border-border hover:bg-muted/50"
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div>
                            <p className="text-sm font-semibold">{type.label}</p>
                            <p className="text-xs text-muted-foreground">{type.desc}</p>
                          </div>
                          <Checkbox checked={dataTypes.includes(type.id)} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Timeframes */}
                {dataTypes.includes("klines") && (
                  <div className="space-y-3">
                    <Label>3. Klines Timeframes</Label>
                    <div className="flex flex-wrap gap-2">
                      {["1m", "5m", "15m", "1h", "4h", "1d"].map((tf) => (
                        <Button
                          key={tf}
                          size="sm"
                          variant={timeframes.includes(tf) ? "default" : "outline"}
                          onClick={() => toggleSelection(tf, timeframes, setTimeframes)}
                        >
                          {tf}
                        </Button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Dates */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <Label>4. Date Range</Label>
                    <div className="flex items-center space-x-2">
                      <Checkbox id="updateMode" checked={updateOnly} onCheckedChange={(c) => setUpdateOnly(!!c)} />
                      <Label htmlFor="updateMode" className="text-xs">Yesterday Only</Label>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1">
                      <span className="text-[10px] text-muted-foreground uppercase font-bold">Start Date</span>
                      <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} disabled={updateOnly} />
                    </div>
                    <div className="space-y-1">
                      <span className="text-[10px] text-muted-foreground uppercase font-bold">End Date</span>
                      <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} disabled={updateOnly} />
                    </div>
                  </div>
                </div>

                {/* Flags */}
                <div className="space-y-3">
                  <Label>5. Execution Flags</Label>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <label className="flex items-start gap-3 p-3 rounded-lg border bg-muted/20 cursor-pointer">
                      <Checkbox checked={enrichOnly} onCheckedChange={(c) => setEnrichOnly(!!c)} className="mt-1" />
                      <div>
                        <p className="text-sm font-semibold">Enrich Only</p>
                        <p className="text-[10px] text-muted-foreground leading-tight">Skip download, only calculate indicators and tape features.</p>
                      </div>
                    </label>
                    <label className="flex items-start gap-3 p-3 rounded-lg border bg-muted/20 cursor-pointer">
                      <Checkbox checked={deleteAggtrades} onCheckedChange={(c) => setDeleteAggtrades(!!c)} className="mt-1" />
                      <div>
                        <p className="text-sm font-semibold">Clean AggTrades</p>
                        <p className="text-[10px] text-muted-foreground leading-tight">Delete raw tick data after enrichment to save disk space.</p>
                      </div>
                    </label>
                  </div>
                </div>
              </CardContent>
            </Card>

            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle>Actions</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex gap-3">
                    {isRunning ? (
                      <Button variant="destructive" className="w-full py-6" onClick={handleStop} disabled={isLoading}>
                        <Square className="mr-2 h-4 w-4" /> Stop Pipeline
                      </Button>
                    ) : (
                      <Button className="w-full py-6 text-lg font-bold" onClick={handleStart} disabled={isLoading}>
                        <Play className="mr-2 h-5 w-5 fill-current" /> Run Pipeline
                      </Button>
                    )}
                  </div>
                  <Button variant="outline" className="w-full" onClick={fetchStorageInfo}>
                    <RefreshCw className="mr-2 h-4 w-4" /> Refresh Storage Map
                  </Button>
                </CardContent>
              </Card>

              <Card className="bg-muted/50 border-dashed">
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-xs uppercase tracking-widest text-muted-foreground font-bold">CLI Command Preview</CardTitle>
                    <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleCopyCommand}>
                      {copied ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
                    </Button>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="bg-black/90 p-3 rounded border font-mono text-[10px] text-blue-400 break-all leading-relaxed">
                    {generateCommand()}
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="storage" className="space-y-6">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle>Storage Map</CardTitle>
                <CardDescription>Available historical data in data_storage/binance/futures</CardDescription>
              </div>
              <div className="flex items-center gap-4">
                <div className="flex items-center space-x-2">
                   <Checkbox 
                     id="catchUpDelete" 
                     checked={catchUpDeleteAggtrades} 
                     onCheckedChange={(c) => setCatchUpDeleteAggtrades(!!c)} 
                   />
                   <Label htmlFor="catchUpDelete" className="text-xs font-medium cursor-pointer">Clean AggTrades</Label>
                </div>
                 <Button 
                   onClick={handleCatchUp} 
                   disabled={isRunning || isLoading} 
                   className="bg-amber-600 hover:bg-amber-700 text-white font-bold gap-2 disabled:opacity-50"
                 >
                   <Zap className="h-4 w-4 fill-current" /> Catch Up All History
                 </Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="rounded-md border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-muted/50 text-left border-b">
                      <th className="p-3 font-semibold">Symbol</th>
                      <th className="p-3 font-semibold">Klines 1m Range</th>
                      <th className="p-3 font-semibold">Size</th>
                      <th className="p-3 font-semibold text-center">Enrichment</th>
                      <th className="p-3 font-semibold">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {storageData.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="p-8 text-center text-muted-foreground">
                          <HardDrive className="h-10 w-10 mx-auto mb-2 opacity-20" />
                          No data found in storage. Start a pipeline to download data.
                        </td>
                      </tr>
                    ) : (
                      storageData.map((s) => (
                        <tr key={s.symbol} className="border-b hover:bg-muted/30 transition-colors">
                          <td className="p-3 font-mono font-bold text-primary">{s.symbol}</td>
                          <td className="p-3">
                            {s.klines_1m ? (
                              <div className="flex flex-col gap-1">
                                <div className="flex items-center gap-2 text-xs">
                                  <Calendar className="h-3 w-3 text-muted-foreground" />
                                  {s.klines_1m.start_date} <span className="text-muted-foreground">→</span> {s.klines_1m.end_date}
                                </div>
                                <div className="flex flex-wrap gap-1">
                                   {s.timeframes.map(tf => (
                                      <Badge key={tf} variant="outline" className="text-[9px] px-1 h-4">{tf}</Badge>
                                   ))}
                                </div>
                              </div>
                            ) : (
                              <span className="text-xs text-destructive flex items-center gap-1">
                                <Search className="h-3 w-3" /> No kline data
                              </span>
                            )}
                          </td>
                          <td className="p-3">
                             <div className="flex flex-col gap-1">
                                <Badge variant="outline" className="font-mono text-[10px] w-fit">
                                  {s.klines_1m ? `${s.klines_1m.size_mb} MB` : "0 MB"}
                                </Badge>
                                {s.has_aggtrades && <span className="text-[9px] text-amber-500 font-bold uppercase">Raw AggTrades Found</span>}
                             </div>
                          </td>
                          <td className="p-3">
                            <div className="flex flex-wrap gap-1 max-w-[200px]">
                               <Badge variant={s.klines_1m?.is_enriched ? "secondary" : "outline"} className={`text-[9px] ${s.klines_1m?.is_enriched ? "bg-green-500/10 text-green-500 border-green-500/20" : "text-muted-foreground"}`}>
                                 TAPE ENRICHED
                               </Badge>
                               <Badge variant={s.has_klines_1s ? "secondary" : "outline"} className={`text-[9px] ${s.has_klines_1s ? "bg-blue-500/10 text-blue-500 border-blue-500/20" : "text-muted-foreground"}`}>
                                 1S KLINES
                               </Badge>
                               <Badge variant={s.has_oi ? "secondary" : "outline"} className={`text-[9px] ${s.has_oi ? "bg-purple-500/10 text-purple-500 border-purple-500/20" : "text-muted-foreground"}`}>
                                 OI METRICS
                               </Badge>
                               <Badge variant={s.has_depth ? "secondary" : "outline"} className={`text-[9px] ${s.has_depth ? "bg-orange-500/10 text-orange-500 border-orange-500/20" : "text-muted-foreground"}`}>
                                 BOOK DEPTH
                               </Badge>
                            </div>
                          </td>
                          <td className="p-3">
                             {s.klines_1m && s.klines_1m.end_date === new Date(Date.now() - 86400000).toISOString().split('T')[0] ? (
                               <Badge className="bg-green-500">Up to date</Badge>
                             ) : s.klines_1m ? (
                               <Badge variant="outline" className="text-amber-500 border-amber-500/30">Behind</Badge>
                             ) : (
                               <Badge variant="secondary">Missing</Badge>
                             )}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="terminal" className="space-y-6">
          <Card className="bg-black border-zinc-800 overflow-hidden shadow-2xl">
             <div className="bg-zinc-900 px-4 py-2 border-b border-zinc-800 flex items-center justify-between">
                <div className="flex items-center gap-2">
                   <div className="flex gap-1.5">
                      <div className="w-3 h-3 rounded-full bg-red-500/80" />
                      <div className="w-3 h-3 rounded-full bg-yellow-500/80" />
                      <div className="w-3 h-3 rounded-full bg-green-500/80" />
                   </div>
                   <span className="text-xs font-mono text-zinc-500 ml-2">bash — download_pipeline.log</span>
                </div>
                {isRunning && (
                  <div className="flex items-center gap-2 text-[10px] text-green-500 font-mono animate-pulse">
                     <RefreshCw className="h-3 w-3 animate-spin" />
                     PROCESS ACTIVE
                  </div>
                )}
             </div>
             <CardContent className="p-0">
               <div className="h-[600px] bg-black text-green-500 p-4 font-mono text-xs overflow-hidden flex flex-col">
                  <ScrollArea className="flex-1">
                    {logs ? (
                      <pre className="whitespace-pre-wrap leading-relaxed">{logs}</pre>
                    ) : (
                      <div className="h-full flex flex-col items-center justify-center text-zinc-700 space-y-4">
                        <TerminalIcon className="h-12 w-12 opacity-10" />
                        <p className="text-sm">No active pipeline logs available.</p>
                      </div>
                    )}
                    <div ref={terminalEndRef} />
                  </ScrollArea>
               </div>
             </CardContent>
             <div className="bg-zinc-900 px-4 py-3 border-t border-zinc-800 flex justify-between items-center">
                <div className="text-[10px] text-zinc-500 uppercase tracking-widest font-bold">
                   Real-time output stream
                </div>
                <div className="flex gap-2">
                   <Button size="sm" variant="outline" className="h-7 bg-transparent border-zinc-700 text-zinc-400 hover:text-white" onClick={() => setLogs("")}>
                      Clear Logs
                   </Button>
                   {isRunning && (
                     <Button size="sm" variant="destructive" className="h-7" onClick={handleStop}>
                        Force Stop
                     </Button>
                   )}
                </div>
             </div>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default DataPipelinePage;
