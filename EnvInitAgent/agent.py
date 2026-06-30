"""Environment initialization agent used by MAPPER."""

import os
import time
from typing import Any, Iterable

from dotenv import load_dotenv
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.prompts.chat import MessagesPlaceholder
from langchain_openai import ChatOpenAI
from loguru import logger

from prompt import ENV_INIT_SYSTEM_PROMPT, ENV_INIT_USER_PROMPT

load_dotenv()


class EnvInitAgent:
    """Call the LLM to infer an initial Python environment."""

    def __init__(self, model_name: str, temperature: float) -> None:
        """Initialize the environment initialization agent.

        Args:
            model_name: Name of the OpenAI-compatible chat model.
            temperature: Sampling temperature used by the model.

        """
        self.model_name = model_name
        self.temperature = temperature
        self.model = self._create_model()

    def _create_model(self) -> ChatOpenAI:
        """Create the chat model used for environment initialization.

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

    def initialize(
        self,
        code: str,
        tools: Iterable[Any],
        policy_system: ENV_INIT_SYSTEM_PROMPT,
        policy_user: ENV_INIT_USER_PROMPT,
    ) -> str:
        """Generate an initial environment description for the supplied code.

        Args:
            code: Python source code to analyze.
            tools: Tools that the agent may call during analysis.
            policy_system: System prompt containing initialization policies.
            policy_user: User prompt template containing the code placeholder.

        Returns:
            Raw model output containing the candidate environment JSON.
        """
        logger.info("[init] Starting environment initialization")

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

        # Invoke the agent and measure the initialization time.
        start_time = time.time()
        result = executor.invoke({"code": code})
        elapsed = time.time() - start_time

        # Normalize the model output.
        llm_output = str(result["output"])
        logger.info(
            f"[init] Environment initialization DONE. Elapsed time: {elapsed:.2f} seconds"
        )
        return llm_output
