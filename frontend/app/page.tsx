"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

type SourceMode = "repository" | "runtime" | "combined";
type DepthMode = "quick" | "examination";
type Domain = "repository" | "functional";
type Phase = "configure" | "preview" | "running" | "report";

type PlanTask = {
  task_id: string;
  agent_id: string;
  objective: string;
  domain: string;
  depends_on: string[];
};

type PlanPreview = {
  mission: Record<string, unknown>;
  plan: {
    summary: string;
    tasks: PlanTask[];
    estimated_duration_seconds: number;
    estimated_requests: number;
    production_restrictions: string[];
  };
  missing_executors: string[];
  executable: boolean;
};

type RunEvent = {
  sequence: number;
  event_type: string;
  agent_id?: string;
  message: string;
  occurred_at: string;
};

type TaskRecord = {
  agent_id: string;
  status: string;
  output?: {
    output_schema: string;
    output: Record<string, unknown>;
  };
};

type RunState = {
  run_id: string;
  status: string;
  mission: Record<string, unknown>;
  plan: PlanPreview["plan"];
  task_records: Record<string, TaskRecord>;
  created_at: string;
  updated_at: string;
  error?: string;
};

type RunSummary = {
  run_id: string;
  objective: string;
  mode: string;
  source: SourceMode;
  status: string;
  agent_count: number;
  completed_agents: number;
  created_at: string;
  updated_at: string;
};

const API = "/control-plane";
const TERMINAL = new Set(["completed", "failed", "cancelled"]);
const EVENT_TYPES = [
  "run.created",
  "run.planned",
  "run.started",
  "run.cancellation_requested",
  "run.completed",
  "run.failed",
  "run.cancelled",
  "agent.started",
  "agent.retrying",
  "agent.completed",
  "agent.failed",
  "agent.skipped",
];

const AGENT_NAMES: Record<string, string> = {
  repository_analyst: "Repository Analyst",
  test_architect: "Test Architect",
  browser_automation_engineer: "Browser Automation",
  evidence_reporting_analyst: "Evidence & Reporting",
  accessibility_specialist: "Accessibility Specialist",
  security_test_engineer: "Security Test Engineer",
  performance_test_engineer: "Performance Engineer",
};

function parseGitHubUrl(value: string) {
  const parsed = new URL(value.trim());
  if (parsed.protocol !== "https:" || parsed.hostname !== "github.com") {
    throw new Error("Usa una URL pública HTTPS de github.com.");
  }
  const parts = parsed.pathname
    .replace(/\.git$/, "")
    .split("/")
    .filter(Boolean);
  if (parts.length !== 2) {
    throw new Error("La URL debe tener el formato github.com/OWNER/REPO.");
  }
  const [owner, name] = parts;
  return {
    repository_id: `github:${owner}/${name}`,
    owner,
    name,
    clone_url: `https://github.com/${owner}/${name}.git`,
    private: false,
  };
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "No fue posible completar la operación.";
}

function agentName(agentId?: string) {
  return agentId ? AGENT_NAMES[agentId] ?? agentId : "QA Director";
}

export default function QaDirectorPage() {
  const [phase, setPhase] = useState<Phase>("configure");
  const [sourceMode, setSourceMode] = useState<SourceMode>("combined");
  const [depth, setDepth] = useState<DepthMode>("examination");
  const [objective, setObjective] = useState(
    "Examinar el flujo principal y correlacionarlo con los riesgos del repositorio",
  );
  const [repositoryUrl, setRepositoryUrl] = useState(
    "https://github.com/octocat/Hello-World",
  );
  const [pullRequest, setPullRequest] = useState("");
  const [runtimeUrl, setRuntimeUrl] = useState("https://example.com");
  const [environment, setEnvironment] = useState("staging");
  const [allowedPaths, setAllowedPaths] = useState("/");
  const [repositoryDomain, setRepositoryDomain] = useState(true);
  const [functionalDomain, setFunctionalDomain] = useState(true);
  const [preview, setPreview] = useState<PlanPreview | null>(null);
  const [run, setRun] = useState<RunState | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const streamRef = useRef<EventSource | null>(null);

  useEffect(() => {
    void loadHistory();
    return () => streamRef.current?.close();
  }, []);

  const hasRepository = sourceMode !== "runtime";
  const hasRuntime = sourceMode !== "repository";
  const selectedDomains = useMemo(() => {
    const domains: Domain[] = [];
    if (hasRepository && repositoryDomain) domains.push("repository");
    if (hasRuntime && functionalDomain) domains.push("functional");
    return domains;
  }, [hasRepository, hasRuntime, repositoryDomain, functionalDomain]);

  function buildMission() {
    if (!objective.trim()) throw new Error("Describe el objetivo de QA.");
    if (!selectedDomains.length) throw new Error("Selecciona al menos un área.");

    const mission: Record<string, unknown> = {
      objective: objective.trim(),
      mode: depth === "quick" ? "quick_task" : "targeted_examination",
    };
    if (hasRepository) {
      mission.repository_target = parseGitHubUrl(repositoryUrl);
      if (pullRequest.trim()) {
        const number = Number(pullRequest);
        if (!Number.isInteger(number) || number <= 0) {
          throw new Error("El número de pull request debe ser positivo.");
        }
        mission.pull_request_number = number;
      }
    }
    if (hasRuntime) {
      const parsedRuntime = new URL(runtimeUrl.trim());
      if (!["http:", "https:"].includes(parsedRuntime.protocol)) {
        throw new Error("El target debe usar HTTP o HTTPS.");
      }
      const paths = allowedPaths
        .split(/\r?\n|,/)
        .map((path) => path.trim())
        .filter(Boolean);
      if (!paths.length || paths.some((path) => !path.startsWith("/"))) {
        throw new Error("Cada ruta permitida debe comenzar con /.");
      }
      mission.runtime_target = {
        base_url: parsedRuntime.toString(),
        environment,
        allowed_paths: paths,
        blocked_paths: ["/admin", "/logout"],
      };
    }
    if (depth === "quick") {
      mission.requested_jobs = selectedDomains.map((domain) => ({
        objective:
          domain === "repository"
            ? "Reconocer componentes y riesgos del repositorio"
            : "Verificar los journeys aprobados en el navegador",
        domains: [domain],
      }));
    } else {
      mission.selected_domains = selectedDomains;
    }
    return mission;
  }

  async function previewPlan(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const mission = buildMission();
      const response = await fetch(`${API}/v1/plans/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(mission),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof payload.detail === "string"
            ? payload.detail
            : "La misión no cumple el contrato seguro.",
        );
      }
      setPreview(payload);
      setPhase("preview");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function refreshRun(runId: string) {
    const response = await fetch(`${API}/v1/runs/${runId}`, {
      cache: "no-store",
    });
    if (!response.ok) return;
    const state: RunState = await response.json();
    setRun(state);
    if (TERMINAL.has(state.status)) {
      streamRef.current?.close();
      setPhase(state.status === "completed" ? "report" : "running");
      void loadHistory();
    }
  }

  async function loadHistory() {
    try {
      const response = await fetch(`${API}/v1/runs?limit=6`, {
        cache: "no-store",
      });
      if (!response.ok) return;
      setHistory(await response.json());
    } catch {
      // The mission form remains usable when the backend is temporarily offline.
    }
  }

  async function openHistoryRun(summary: RunSummary) {
    setBusy(true);
    setError("");
    streamRef.current?.close();
    try {
      const [stateResponse, eventsResponse] = await Promise.all([
        fetch(`${API}/v1/runs/${summary.run_id}`, { cache: "no-store" }),
        fetch(`${API}/v1/runs/${summary.run_id}/events`, { cache: "no-store" }),
      ]);
      if (!stateResponse.ok || !eventsResponse.ok) {
        throw new Error("No fue posible recuperar este análisis.");
      }
      const state: RunState = await stateResponse.json();
      setRun(state);
      setPreview({
        mission: state.mission,
        plan: state.plan,
        missing_executors: [],
        executable: true,
      });
      setEvents(await eventsResponse.json());
      setPhase(state.status === "completed" ? "report" : "running");
      if (!TERMINAL.has(state.status)) {
        openEventStream(
          state.run_id,
          `/v1/runs/${state.run_id}/events/stream`,
        );
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  function openEventStream(runId: string, streamUrl: string) {
    streamRef.current?.close();
    const stream = new EventSource(`${API}${streamUrl}`);
    EVENT_TYPES.forEach((eventType) => {
      stream.addEventListener(eventType, (message) => {
        const event = JSON.parse((message as MessageEvent).data) as RunEvent;
        setEvents((current) => {
          if (current.some((item) => item.sequence === event.sequence)) return current;
          return [...current, event].sort((a, b) => a.sequence - b.sequence);
        });
        void refreshRun(runId);
      });
    });
    stream.onerror = () => void refreshRun(runId);
    streamRef.current = stream;
  }

  async function launchRun() {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/v1/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mission: preview.mission, approved: true }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail?.message ?? "El run no fue aceptado.");
      }
      setPhase("running");
      setEvents([]);
      await refreshRun(payload.run_id);
      await loadHistory();
      openEventStream(payload.run_id, payload.event_stream_url);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function cancelRun() {
    if (!run) return;
    await fetch(`${API}/v1/runs/${run.run_id}/cancel`, { method: "POST" });
    await refreshRun(run.run_id);
  }

  function reset() {
    streamRef.current?.close();
    setPreview(null);
    setRun(null);
    setEvents([]);
    setError("");
    setPhase("configure");
  }

  const recordsByAgent = useMemo(() => {
    return Object.values(run?.task_records ?? {}).reduce<Record<string, TaskRecord>>(
      (result, record) => {
        result[record.agent_id] = record;
        return result;
      },
      {},
    );
  }, [run]);

  const repositoryOutput = recordsByAgent.repository_analyst?.output?.output as
    | {
        project_profile?: {
          project_type: string;
          components: Array<{
            component_id: string;
            path: string;
            component_type: string;
            languages: Array<{ name: string }>;
            frameworks: Array<{ name: string }>;
          }>;
        };
      }
    | undefined;
  const reportOutput = recordsByAgent.evidence_reporting_analyst?.output?.output as
    | {
        report?: {
          execution_summary: string;
          findings: Array<{
            primary_finding: {
              finding_id: string;
              title: string;
              severity: string;
              observation: string;
              affected_locations: string[];
            };
            correlation_reason: string;
          }>;
          residual_risks: string[];
        };
      }
    | undefined;

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brandMark">S</span>
          <div>
            <strong>SWARM AI QA</strong>
            <small>QA Director Console</small>
          </div>
        </div>
        <div className="boundary">
          <span className="pulse" />
          READ-ONLY BOUNDARY ACTIVE
        </div>
      </header>

      <section className="hero">
        <div>
          <span className="eyebrow">MISSION CONTROL / 01</span>
          <h1>Dirige QA como un equipo,<br />no como una lista de herramientas.</h1>
          <p>
            Define el objetivo. QA Director reconoce el proyecto, selecciona
            especialistas y conserva evidencia verificable sin tocar el código.
          </p>
        </div>
        <div className="heroMetric">
          <span>PRODUCT BOUNDARY</span>
          <strong>0</strong>
          <small>archivos del usuario modificados</small>
        </div>
      </section>

      <div className="workspace">
        <aside className="rail">
          {[
            ["01", "Objetivo", "configure"],
            ["02", "Plan del enjambre", "preview"],
            ["03", "Ejecución real", "running"],
            ["04", "Evidencia", "report"],
          ].map(([number, label, target]) => {
            const order = ["configure", "preview", "running", "report"];
            const active = order.indexOf(phase) >= order.indexOf(target as Phase);
            return (
              <div className={`railStep ${active ? "active" : ""}`} key={number}>
                <span>{number}</span>
                <p>{label}</p>
              </div>
            );
          })}
          <div className="railRule" />
          <p className="railNote">
            Cada estado proviene del backend. No hay agentes ni actividad simulada.
          </p>
          <div className="history">
            <div className="historyTitle">
              <span>HISTORIAL NEON</span>
              <small>{history.length}</small>
            </div>
            {history.map((item) => (
              <button
                className={`historyRun ${run?.run_id === item.run_id ? "selected" : ""}`}
                disabled={busy}
                key={item.run_id}
                onClick={() => void openHistoryRun(item)}
                type="button"
              >
                <span>
                  {item.source} · {item.status}
                </span>
                <strong>{item.objective}</strong>
                <small>
                  {item.completed_agents}/{item.agent_count} agentes ·{" "}
                  {new Date(item.updated_at).toLocaleDateString()}
                </small>
              </button>
            ))}
            {!history.length && (
              <p className="historyEmpty">Los análisis terminados aparecerán aquí.</p>
            )}
          </div>
        </aside>

        <section className="content">
          {phase === "configure" && (
            <form onSubmit={previewPlan}>
              <div className="sectionHeading">
                <div>
                  <span className="eyebrow">CONFIGURAR MISIÓN</span>
                  <h2>¿Qué quieres examinar?</h2>
                </div>
                <span className="stepCounter">PASO 1 DE 4</span>
              </div>

              <div className="sourceGrid">
                {[
                  ["repository", "Repositorio", "Código, manifests y pull request", "⌘"],
                  ["runtime", "Producción", "Rutas públicas y comportamiento real", "↗"],
                  ["combined", "Ambos", "Correlación repo + runtime", "⤮"],
                ].map(([value, label, detail, icon]) => (
                  <button
                    type="button"
                    key={value}
                    className={`sourceCard ${sourceMode === value ? "selected" : ""}`}
                    onClick={() => setSourceMode(value as SourceMode)}
                  >
                    <span className="sourceIcon">{icon}</span>
                    <strong>{label}</strong>
                    <small>{detail}</small>
                  </button>
                ))}
              </div>

              <label className="field full">
                <span>OBJETIVO DE QA</span>
                <textarea
                  value={objective}
                  onChange={(event) => setObjective(event.target.value)}
                  rows={3}
                />
              </label>

              <div className="formGrid">
                {hasRepository && (
                  <>
                    <label className="field spanTwo">
                      <span>REPOSITORIO PÚBLICO GITHUB</span>
                      <input
                        value={repositoryUrl}
                        onChange={(event) => setRepositoryUrl(event.target.value)}
                        placeholder="https://github.com/owner/repo"
                      />
                    </label>
                    <label className="field">
                      <span>PULL REQUEST <i>OPCIONAL</i></span>
                      <input
                        value={pullRequest}
                        onChange={(event) => setPullRequest(event.target.value)}
                        inputMode="numeric"
                        placeholder="42"
                      />
                    </label>
                  </>
                )}
                {hasRuntime && (
                  <>
                    <label className="field spanTwo">
                      <span>URL AUTORIZADA</span>
                      <input
                        value={runtimeUrl}
                        onChange={(event) => setRuntimeUrl(event.target.value)}
                        placeholder="https://staging.example.com"
                      />
                    </label>
                    <label className="field">
                      <span>ENTORNO</span>
                      <select
                        value={environment}
                        onChange={(event) => setEnvironment(event.target.value)}
                      >
                        <option value="sandbox">Sandbox</option>
                        <option value="staging">Staging</option>
                        <option value="production">Producción</option>
                      </select>
                    </label>
                    <label className="field full">
                      <span>RUTAS PERMITIDAS <i>UNA POR LÍNEA</i></span>
                      <textarea
                        value={allowedPaths}
                        onChange={(event) => setAllowedPaths(event.target.value)}
                        rows={2}
                        placeholder={"/\n/checkout"}
                      />
                    </label>
                  </>
                )}
              </div>

              <div className="choiceSection">
                <span className="label">PROFUNDIDAD</span>
                <div className="depthGrid">
                  <button
                    type="button"
                    className={depth === "quick" ? "depth selected" : "depth"}
                    onClick={() => setDepth("quick")}
                  >
                    <span>01–02</span>
                    <div>
                      <strong>Trabajo rápido</strong>
                      <small>Uno o dos encargos concretos</small>
                    </div>
                  </button>
                  <button
                    type="button"
                    className={depth === "examination" ? "depth selected" : "depth"}
                    onClick={() => setDepth("examination")}
                  >
                    <span>ALL</span>
                    <div>
                      <strong>Examen coordinado</strong>
                      <small>Todas las áreas conectadas hoy</small>
                    </div>
                  </button>
                </div>
              </div>

              <div className="choiceSection">
                <span className="label">ÁREAS DISPONIBLES</span>
                <div className="domainRow">
                  {hasRepository && (
                    <label className="domainChip">
                      <input
                        type="checkbox"
                        checked={repositoryDomain}
                        onChange={(event) => setRepositoryDomain(event.target.checked)}
                      />
                      <span>Repository intelligence</span>
                    </label>
                  )}
                  {hasRuntime && (
                    <label className="domainChip">
                      <input
                        type="checkbox"
                        checked={functionalDomain}
                        onChange={(event) => setFunctionalDomain(event.target.checked)}
                      />
                      <span>Browser functional</span>
                    </label>
                  )}
                  {["Accessibility", "Security", "Performance"].map((domain) => (
                    <span className="domainChip disabled" key={domain}>
                      {domain} · próximo
                    </span>
                  ))}
                </div>
              </div>

              {error && <div className="errorBox">{error}</div>}
              <div className="actionRow">
                <p>
                  Antes de ejecutar verás agentes, límites y presupuesto estimado.
                </p>
                <button className="primary" disabled={busy}>
                  {busy ? "ANALIZANDO…" : "GENERAR PLAN"}
                  <span>→</span>
                </button>
              </div>
            </form>
          )}

          {phase === "preview" && preview && (
            <section>
              <div className="sectionHeading">
                <div>
                  <span className="eyebrow">PLAN TRAZABLE</span>
                  <h2>Este es el equipo propuesto.</h2>
                </div>
                <button className="textButton" onClick={reset}>EDITAR MISIÓN</button>
              </div>
              <div className="planSummary">
                <p>{preview.plan.summary}</p>
                <div>
                  <span><strong>{preview.plan.tasks.length}</strong> agentes</span>
                  <span><strong>{preview.plan.estimated_requests}</strong> requests máx.</span>
                  <span><strong>~{Math.ceil(preview.plan.estimated_duration_seconds / 60)}</strong> min</span>
                </div>
              </div>
              <div className="agentStack">
                {preview.plan.tasks.map((task, index) => (
                  <article className="agentCard" key={task.task_id}>
                    <span className="agentIndex">{String(index + 1).padStart(2, "0")}</span>
                    <div className="agentAvatar">{agentName(task.agent_id).slice(0, 2).toUpperCase()}</div>
                    <div>
                      <strong>{agentName(task.agent_id)}</strong>
                      <p>{task.objective}</p>
                    </div>
                    <span className="status planned">PLANNED</span>
                  </article>
                ))}
              </div>
              {!!preview.plan.production_restrictions.length && (
                <div className="restrictionBox">
                  <strong>RESTRICCIONES DE PRODUCCIÓN</strong>
                  {preview.plan.production_restrictions.map((restriction) => (
                    <p key={restriction}>— {restriction}</p>
                  ))}
                </div>
              )}
              {!!preview.missing_executors.length && (
                <div className="errorBox">
                  Faltan executors reales: {preview.missing_executors.join(", ")}.
                  El run permanecerá bloqueado.
                </div>
              )}
              {error && <div className="errorBox">{error}</div>}
              <div className="actionRow">
                <p>La aprobación inicia trabajo real de QA estrictamente read-only.</p>
                <button
                  className="primary"
                  onClick={launchRun}
                  disabled={busy || !preview.executable}
                >
                  {busy ? "INICIANDO…" : "APROBAR Y EJECUTAR"}
                  <span>▶</span>
                </button>
              </div>
            </section>
          )}

          {(phase === "running" || phase === "report") && run && (
            <section>
              <div className="sectionHeading">
                <div>
                  <span className="eyebrow">RUN / {run.run_id.slice(0, 8)}</span>
                  <h2>
                    {phase === "report"
                      ? "La evidencia está lista."
                      : "El enjambre está trabajando."}
                  </h2>
                </div>
                <span className={`runStatus ${run.status}`}>{run.status}</span>
              </div>

              <div className="liveGrid">
                <div className="agentStack">
                  {preview?.plan.tasks.map((task, index) => {
                    const record = recordsByAgent[task.agent_id];
                    return (
                      <article className="agentCard" key={task.task_id}>
                        <span className="agentIndex">{String(index + 1).padStart(2, "0")}</span>
                        <div className="agentAvatar">{agentName(task.agent_id).slice(0, 2).toUpperCase()}</div>
                        <div>
                          <strong>{agentName(task.agent_id)}</strong>
                          <p>{task.objective}</p>
                        </div>
                        <span className={`status ${record?.status ?? "pending"}`}>
                          {record?.status ?? "pending"}
                        </span>
                      </article>
                    );
                  })}
                </div>
                <aside className="eventLog">
                  <div className="eventHeader">
                    <span>LIVE EVENT STREAM</span>
                    <i className={TERMINAL.has(run.status) ? "dot stopped" : "dot"} />
                  </div>
                  <div className="events">
                    {events.map((event) => (
                      <div className="event" key={event.sequence}>
                        <time>{new Date(event.occurred_at).toLocaleTimeString()}</time>
                        <strong>{agentName(event.agent_id)}</strong>
                        <p>{event.message}</p>
                      </div>
                    ))}
                    {!events.length && <p className="empty">Esperando eventos reales…</p>}
                  </div>
                </aside>
              </div>

              {phase === "report" && (
                <div className="reportArea">
                  {repositoryOutput?.project_profile && (
                    <section className="reportBlock">
                      <div className="blockTitle">
                        <span>PROJECT INTELLIGENCE</span>
                        <strong>{repositoryOutput.project_profile.project_type}</strong>
                      </div>
                      <div className="componentGrid">
                        {repositoryOutput.project_profile.components.map((component) => (
                          <article className="componentCard" key={component.component_id}>
                            <small>{component.path}</small>
                            <strong>{component.component_id}</strong>
                            <span>{component.component_type}</span>
                            <p>
                              {[...component.languages, ...component.frameworks]
                                .map((item) => item.name)
                                .join(" · ")}
                            </p>
                          </article>
                        ))}
                      </div>
                    </section>
                  )}

                  {reportOutput?.report && (
                    <section className="reportBlock">
                      <div className="blockTitle">
                        <span>EVIDENCE REPORT</span>
                        <strong>
                          {reportOutput.report.findings.length} findings
                        </strong>
                      </div>
                      <p className="executionSummary">
                        {reportOutput.report.execution_summary}
                      </p>
                      {reportOutput.report.findings.map(({ primary_finding, correlation_reason }) => (
                        <article className="finding" key={primary_finding.finding_id}>
                          <span className={`severity ${primary_finding.severity}`}>
                            {primary_finding.severity}
                          </span>
                          <div>
                            <strong>{primary_finding.title}</strong>
                            <p>{primary_finding.observation}</p>
                            <small>{correlation_reason}</small>
                          </div>
                        </article>
                      ))}
                      {!reportOutput.report.findings.length && (
                        <div className="cleanResult">
                          No se produjeron findings con la evidencia ejecutada.
                          Esto no equivale a ausencia total de defectos.
                        </div>
                      )}
                    </section>
                  )}
                </div>
              )}

              {error && <div className="errorBox">{error}</div>}
              <div className="actionRow">
                <p>
                  {run.error ?? "Los agentes nunca escriben en el repositorio evaluado."}
                </p>
                {TERMINAL.has(run.status) ? (
                  <button className="primary" onClick={reset}>
                    NUEVA MISIÓN <span>＋</span>
                  </button>
                ) : (
                  <button className="danger" onClick={cancelRun}>
                    CANCELAR DE FORMA SEGURA
                  </button>
                )}
              </div>
            </section>
          )}
        </section>
      </div>

      <footer>
        <span>SWARM AI QA / HACKATHON BUILD</span>
        <span>EVIDENCE FIRST · CODE UNTOUCHED</span>
      </footer>
    </main>
  );
}
