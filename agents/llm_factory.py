"""
LLM factory — returns an OpenAI or Ollama chat model based on env config.
"""
import os
from langchain_openai import ChatOpenAI
from langchain_community.chat_models import ChatOllama

def get_llm():
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider == "ollama":
        return ChatOllama(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            model=os.getenv("OLLAMA_MODEL", "llama3"),
            temperature=0,
            format="json",
        )
    return ChatOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        temperature=0,
    )
