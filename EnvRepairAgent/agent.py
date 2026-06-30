"""Environment repair agent used by MAPPER."""

import os
import time
from typing import Any, Dict, Iterable

from dotenv import load_dotenv
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.prompts.chat import MessagesPlaceholder
from langchain_openai import ChatOpenAI
from loguru import logger

from prompt import ENV_REPAIR_SYSTEM_PROMPT, ENV_REPAIR_USER_PROMPT

load_dotenv()


class EnvRepairAgent:
    """Repair a Python environment according to a validation error."""

    def __init__(self, model_name: str, temperature: float) -> None:
        """Initialize the environment repair agent.

        Args:
            model_name: Name of the OpenAI-compatible chat model.
            temperature: Sampling temperature used by the model.

        """
        self.model_name = model_name
        self.temperature = temperature
        self.model = self._create_model()

    def _create_model(self) -> ChatOpenAI:
        """Create the chat model used for environment repair.

        Returns:
            Configured OpenAI-compatible chat model.
        """
        logger.info(f"[llm] Initializing model: {self.model_name}")
        model = ChatOpenAI(
            model=self.model_name,
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL"),
            temperature=self.temperature,
        )
        logger.info("[llm] Model initialization completed")
        return model

    def repair(
        self,
        code: str,
        last_env: Dict[str, Any],
        last_error: str,
        tools: Iterable[Any],
        policy_system: ENV_REPAIR_SYSTEM_PROMPT,
        policy_user: ENV_REPAIR_USER_PROMPT,
    ) -> str:
        """Generate a repaired environment configuration.

        Args:
            code: Python source code whose environment requires repair.
            last_env: Most recently inferred environment configuration.
            last_error: Error produced while validating the current environment.
            tools: Tools that the agent may call during repair.
            policy_system: System prompt containing repair policies.
            policy_user: User prompt template containing input placeholders.

        Returns:
            Raw model output containing a repaired environment JSON or the
            uncontrollable-factor sentinel.
        """
        logger.info("[repair] Starting environment repair")

        tool_list = list(tools)

        # Build the prompt used by the tool-calling agent.
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", policy_system),
                ("user", policy_user),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )

        # Create the tool-calling agent.
        agent = create_tool_calling_agent(
            llm=self.model,
            tools=tool_list,
            prompt=prompt,
        )

        # Create the executor responsible for running the agent.
        executor = AgentExecutor(
            agent=agent,
            tools=tool_list,
            verbose=True,
            stream_runnable=False,
            return_intermediate_steps=True,
        )

        # Invoke the agent and measure the repair time.
        start_time = time.time()
        result = executor.invoke(
            {
                "code": code,
                "code_env": last_env,
                "error_log": last_error,
            }
        )
        elapsed = time.time() - start_time

        # Normalize the model output before returning it.
        llm_output = str(result["output"])
        intermediate_steps = result.get("intermediate_steps", [])
        logger.info(
            f"[repair] Environment repair DONE. Tool trace: {intermediate_steps} Elapsed time: {elapsed:.2f} seconds"
        )

        return llm_output
