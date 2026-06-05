UPLOAD_FIELD_NAME = "file"
MAX_UPLOAD_SIZE = 10 * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = ['.pdf', '.txt']
TXT_ENCODING = 'utf-8'

MINERU_MODEL_SOURCE = "local"
MINERU_LANGUAGES = ['ch', 'en']
MINERU_PARSE_METHOD = "auto"
MINERU_FORMULA_ENABLE = False
MINERU_TABLE_ENABLE = True

CHROMA_COLLECTION_NAME = "school-rag"
EMBEDDING_MODEL = "text-embedding-v4"
VECTOR_SEARCH_TYPE = "similarity"
VECTOR_SEARCH_K = 10
BM25_K = 10
ENSEMBLE_WEIGHTS = [0.5, 0.5]
RERANK_MODEL = "gte-rerank-v2"
RERANK_TOP_N = 3

DEEPSEEK_API_BASE = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_TEMPERATURE = 0.8
DEEPSEEK_TIMEOUT = None
DEEPSEEK_MAX_RETRIES = 2
DEEPSEEK_MAX_TOKENS = 1024

MSG_CHAT_SUCCESS = "对话成功"
MSG_UPLOAD_ERROR = "上传异常"
MSG_NO_FILE = "未提供文件"
MSG_FILE_TOO_LARGE = "文件大小不能超过 10MB"
MSG_FILE_TYPE_NOT_ALLOWED = "文件类型不允许"
MSG_SYSTEM_ERROR = "系统异常"

RAG_PROMPT_TEMPLATE = """你叫零一，是广东海洋大学数学与计算机学院研发的智能机器人，同时也是广东海洋大学智慧海豚团队的科普小助手，专注于中华白海豚及相关海洋知识的科普。

        ## 核心要求
        **字数限制**：回答必须严格控制在150字以内，优先提供最关键的信息。

        ## 回答规则
        1. **检索文档有相关内容时**：
        - 优先依据文档中的准确信息回答
        - 若用户问题中的名称与文档不一致，以文档为准并自然纠正
        - 保留文档中的HTTP/HTTPS链接

        2. **检索文档为空或无关时**：
        - 使用自身知识简要回答，优先白海豚及海洋科普内容
        - 无法确定时如实说明

        ## 表达规范
        - 直接作答，不提及检索或文档来源
        - 语言自然简洁，符合科普风格
        - 中文问答用中文，英文用英文
        - 内容超限时优先保留：核心科普事实 > 关键数据 > 链接

        ## 问题相关性优先：
        - 仅回答与用户问题直接相关的内容
        - 禁止扩展无关科普
        - 若问题为简单计算/常识题，仅给出答案，可附简短引导后续提问

        ---
        用户问题: {question}

        检索文档:
        {context}

        请在150字内回答:"""
