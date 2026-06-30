import os


os.environ.update(
    {
        "TESTING": "true",
        "EMBEDDING_PROVIDER": "mock-hash",
        "EMBEDDING_DIMENSION": "384",
        "EMBEDDING_API_KEY": "",
        "OPENAI_API_KEY": "",
        "SILICONFLOW_API_KEY": "",
        "LLM_PROVIDER": "mock",
        "LLM_API_KEY": "",
        "RERANK_API_KEY": "",
        "RERANK_URL": "",
        "RERANK_MODEL": "",
        "JINA_API_KEY": "",
        "MILVUS_URI": "http://127.0.0.1:1",
    }
)
