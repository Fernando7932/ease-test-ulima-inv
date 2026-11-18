import tools
from google.adk.agents.llm_agent import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from prompt import get_system_prompt, get_user_query


async def run_agent_execution(
    record,
    defense_level: str = "D0",
    user_query: str | None = None,
    model_name: str = "gemini-2.5-flash",
    mailbox: list | None = None,
) -> dict:
    """Ejecuta una corrida del agente agéntico usando el Google Agent Development Kit (ADK)."""

    # 1. Si no se especificó user_query, derivarlo dinámicamente según el escenario del registro
    if user_query is None:
        user_query = get_user_query(record)

    # 2. Cargar el buzón en el contexto local de tools.py (mailbox completo o solo el registro)
    if mailbox is not None:
        tools.set_current_emails(mailbox)
    else:
        tools.set_current_emails(record)

    # 3. Obtener el System Prompt según el nivel defensivo (D0, D1, D2, D3)
    system_prompt = get_system_prompt(defense_level)

    print("\n==================================================")
    print(f" EJECUTANDO AGENTE ADK LOCAL | Nivel: {defense_level} | Modelo: {model_name}")
    print("==================================================")
    print(f"Petición del usuario: '{user_query}'\n")

    try:
        # 4. Instanciar el agente con Google ADK
        email_agent = Agent(
            model=model_name,
            name="gmail_assistant_agent",
            description="Un asistente autónomo de Gmail para gestión de correos.",
            instruction=system_prompt,
            tools=[tools.get_unread_emails, tools.read_email, tools.send_email],
        )

        # 5. Setup session handling required by standard ADK runners
        session_service = InMemorySessionService()

        # DEFINIR IDENTIFICADORES DE CONTEXTO ÚNICOS POR ENSAYO
        user_id = "local-eval-user"
        row_key_safe = str(record.get("RowKey", "run"))[:8] if isinstance(record, dict) else "run"
        session_id = f"eval-{row_key_safe}-{defense_level}"

        # CREAR LA SESIÓN EXPLÍCITAMENTE ANTES DE PASARLA AL RUNNER
        await session_service.create_session(app_name="gmail_assistant_app", user_id=user_id, session_id=session_id)

        # 6. Orquestar la ejecución mediante el Runner de ADK con argumentos requeridos
        runner = Runner(
            app_name="gmail_assistant_app",
            agent=email_agent,
            session_service=session_service,
        )

        # 7. Formatear la consulta como el tipo de entrada de contenido estructurado
        user_content = types.Content(role="user", parts=[types.Part.from_text(text=user_query)])

        # 8. Obtener el generador asíncrono usando la ejecución de stream nativa de ADK
        response_generator = runner.run_async(user_id=user_id, session_id=session_id, new_message=user_content)

        # 9. Consumir el generador asíncrono interpretando la estructura oficial de ADK
        response_text = ""
        print("🤖 Agente procesando...", flush=True)

        async for event in response_generator:
            # Capturar la respuesta definitiva cuando el ciclo de invocación finalice
            if event.is_final_response():
                if event.content and event.content.parts:
                    response_text = event.content.parts[0].text
                    print(f"\n🤖 Agente respondió:\n{response_text}")

        # Si el stream terminó sin un final_response explícito, buscar fallback text
        if not response_text:
            response_text = "El agente procesó la consulta pero no generó texto final."

        return {"status": "completed", "defense_level": defense_level, "user_query": user_query, "response_text": response_text, "raw_response": response_text}

    except Exception as e:
        print(f"❌ Error durante la ejecución del agente en Google ADK: {e}")
        return {"status": "error", "defense_level": defense_level, "user_query": user_query, "error": str(e)}
