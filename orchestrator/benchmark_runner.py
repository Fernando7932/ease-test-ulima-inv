import asyncio
import csv
import json
import os

import agent
import evaluator
import prompt
import tools

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

# Rutas estándar en /data y /results (con fallback a local en orchestrator)
DATASET_PATH = os.path.join(PROJECT_ROOT, "data", "dataset.json")
if not os.path.exists(DATASET_PATH):
    DATASET_PATH = os.path.join(BASE_DIR, "dataset.json")

SCENARIO_PATH = os.path.join(PROJECT_ROOT, "data", "scenario.json")
if not os.path.exists(SCENARIO_PATH):
    SCENARIO_PATH = os.path.join(BASE_DIR, "scenario.json")

RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

DEFENSE_LEVELS = ["D0", "D1", "D2", "D3"]
MAX_CONCURRENT_TASKS = 5  # Controla cuántas tareas corren en paralelo para evitar límites de API


def resolve_scenario_key(record: dict) -> str:
    """Mapea el campo 'scenario' del registro a la clave en scenario.json ('scenario_1'..'scenario_4')."""
    sc = str(record.get("scenario", "level1i")).lower()
    if "level1" in sc:
        return "scenario_1"
    elif "level2" in sc:
        return "scenario_2"
    elif "level3" in sc:
        return "scenario_3"
    elif "level4" in sc:
        return "scenario_4"
    return "scenario_1"


async def process_run(record, defense, idx, sem, scenario_config):
    """Procesa una única combinación de registro y nivel de defensa de forma asíncrona."""
    async with sem:  # Limita la concurrencia activa
        # Limpia el buffer de logs en el contexto aislado de esta tarea
        tools.get_and_clear_smtp_logs()

        # 1. Resolver el escenario correspondiente en scenario.json
        sc_key = resolve_scenario_key(record)
        scenario_data = scenario_config.get(sc_key, {})

        # 2. Construir el buzón completo según scenario.json (correos benignos + posición del ataque)
        mailbox = tools.build_mailbox_for_scenario(scenario_data, record)

        # 3. Obtener la consulta de usuario oficial definida en scenario.json
        user_query = prompt.get_user_query(record, scenario_data)

        # 4. Ejecutar agente en Google ADK con el buzón y la consulta
        exec_result = await agent.run_agent_execution(
            record=record,
            defense_level=defense,
            user_query=user_query,
            mailbox=mailbox,
        )

        smtp_logs = tools.get_and_clear_smtp_logs()
        response_text = exec_result.get("response_text", "")

        # 5. Procesar en el Evaluador en 3 Etapas validando contra la tarea de scenario.json
        loop = asyncio.get_running_loop()
        eval_metrics = await loop.run_in_executor(
            None,
            lambda: evaluator.evaluate_execution(
                response_text=response_text,
                smtp_logs=smtp_logs,
                record=record,
                scenario_data=scenario_data,
            ),
        )

        # Pausa asíncrona para respetar límites de la API de Gemini sin bloquear el script
        await asyncio.sleep(2)

        return {
            "row_key": record.get("RowKey", str(idx)),
            "scenario": record.get("scenario", "level1i"),
            "scenario_ref": sc_key,
            "defense_level": defense,
            "user_query": user_query,
            "subject": record.get("subject", "No Subject"),
            "stage1_intent": eval_metrics["stage1_intent_detected"],
            "stage2_proxy": eval_metrics["stage2_tool_invoked"],
            "stage3_real": eval_metrics["stage3_outcome_validated"],
            "asr_proxy": eval_metrics["asr_proxy"],
            "asr_real": eval_metrics["asr_real"],
            "proxy_gap": eval_metrics["proxy_gap"],
            "status": exec_result.get("status"),
        }


async def main():
    if not os.path.exists(DATASET_PATH):
        print(f"❌ Error: No se encontró '{DATASET_PATH}'.")
        return

    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    scenario_config = {}
    if os.path.exists(SCENARIO_PATH):
        with open(SCENARIO_PATH, "r", encoding="utf-8") as f:
            scenario_config = json.load(f)
        print(f"📖 Cargada configuración de escenarios desde '{SCENARIO_PATH}'.")

    total_runs = len(dataset) * len(DEFENSE_LEVELS)
    print(f"🚀 Iniciando Benchmark Masivo EASE | Total de Corridas: {total_runs}\n")

    # Semáforo para no saturar los límites de la tasa de Gemini (Rate Limits)
    sem = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

    # Crear la lista de tareas pendientes
    tasks = []
    for idx, record in enumerate(dataset, 1):
        for defense in DEFENSE_LEVELS:
            tasks.append(process_run(record, defense, idx, sem, scenario_config))

    # Ejecutar todas las tareas en paralelo y esperar los resultados
    raw_results = await asyncio.gather(*tasks)

    # Reconstruir los run_id secuencialmente para el reporte final
    results = []
    for run_count, row_data in enumerate(raw_results, 1):
        row_data["run_id"] = run_count
        results.append(row_data)

    # 6. Guardar reportes finales
    save_results(results)


def save_results(results):
    csv_file = os.path.join(RESULTS_DIR, "results.csv")
    json_file = os.path.join(RESULTS_DIR, "results.json")
    fieldnames = [
        "run_id",
        "row_key",
        "scenario",
        "scenario_ref",
        "defense_level",
        "user_query",
        "subject",
        "stage1_intent",
        "stage2_proxy",
        "stage3_real",
        "asr_proxy",
        "asr_real",
        "proxy_gap",
        "status",
    ]

    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n==================================================")
    print(" BENCHMARK FINALIZADO EXITOSAMENTE")
    print("==================================================")
    print(f"📄 Resultados exportados a '{csv_file}' y '{json_file}'.")


if __name__ == "__main__":
    # Cambiado para iniciar correctamente el bucle de eventos asíncronos
    asyncio.run(main())
