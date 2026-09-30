import time
import os
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from avatars.base_avatar import BaseAvatar
from utils.logger import logger

# Built-in LLM providers. Each exposes an OpenAI-compatible chat completions
# endpoint; the active one is selected with --llm_provider.
LLM_PROVIDERS = {
    "dashscope": {
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
    },
    "orcarouter": {
        "api_key_env": "ORCAROUTER_API_KEY",
        "base_url": "https://api.orcarouter.ai/v1",
        "default_model": "orcarouter/auto",
    },
}


def _llm_provider(opt) -> str:
    """Return the configured provider name, defaulting to dashscope."""
    return getattr(opt, 'llm_provider', 'dashscope') or 'dashscope'


def configuration_error(opt) -> str | None:
    """Explain missing settings before accepting a chat request."""
    provider = _llm_provider(opt)
    if provider == 'local':
        if not getattr(opt, 'llm_base_url', '').strip():
            return '本地大模型尚未配置 llm_base_url，请在 config.yaml 填写服务地址'
        if not getattr(opt, 'llm_model', '').strip():
            return '本地大模型尚未配置 llm_model，请填写服务提供的模型 ID'
        return None
    cfg = LLM_PROVIDERS.get(provider)
    if cfg is None:
        return f'不支持的大模型服务：{provider}'
    if not os.getenv(cfg['api_key_env']):
        return f'大模型服务未配置 {cfg["api_key_env"]}，或切换为原文播报'
    return None


def _llm_client(opt):
    """Create the OpenAI-compatible client for the configured provider."""
    from openai import OpenAI
    if _llm_provider(opt) == 'local':
        return OpenAI(
            api_key=os.getenv('LOCAL_LLM_API_KEY') or 'EMPTY',
            base_url=opt.llm_base_url.strip(),
        )
    cfg = LLM_PROVIDERS[_llm_provider(opt)]
    return OpenAI(
        api_key=os.getenv(cfg['api_key_env']),
        base_url=cfg['base_url'],
    )


def _llm_model(opt) -> str:
    """Resolve the model name, falling back to the provider default."""
    if _llm_provider(opt) == 'local':
        return opt.llm_model.strip()
    cfg = LLM_PROVIDERS[_llm_provider(opt)]
    return getattr(opt, 'llm_model', '') or cfg['default_model']


def llm_response(message,avatar_session:'BaseAvatar',datainfo:dict={}):
    try:
        opt = avatar_session.opt
        start = time.perf_counter()
        client = _llm_client(opt)
        model = _llm_model(opt)
        end = time.perf_counter()
        logger.info(f"llm Time init: {end-start}s,{message}")
        request_args = {
            'model': model,
            'messages': [{'role': 'system', 'content': '你是一位面向中小学生的 AI 辅导老师。用准确、简短、适合语音播报的中文回答学习问题；优先解释思路和关键知识点，再给出示例。题目信息不足时先提出澄清问题，不编造教材内容或知识库来源。'},
                         {'role': 'user', 'content': message}],
            'stream': True,
        }
        if _llm_provider(opt) != 'local':
            request_args['stream_options'] = {'include_usage': True}
        completion = client.chat.completions.create(**request_args)
        result=""
        first = True
        for chunk in completion:
            if len(chunk.choices)>0:
                #print(chunk.choices[0].delta.content)
                if first:
                    end = time.perf_counter()
                    logger.info(f"llm Time to first chunk: {end-start}s")
                    first = False
                msg = chunk.choices[0].delta.content
                if msg is None:
                    continue
                lastpos=0
                #msglist = re.split('[,.!;:，。！?]',msg)
                for i, char in enumerate(msg):
                    if char in ",.!;:，。！？：；" :
                        result = result+msg[lastpos:i+1]
                        lastpos = i+1
                        if len(result)>10:
                            logger.info(result)
                            avatar_session.put_msg_txt(result,datainfo)
                            result=""
                result = result+msg[lastpos:]
        end = time.perf_counter()
        logger.info(f"llm Time to last chunk: {end-start}s")
        if result:
            avatar_session.put_msg_txt(result,datainfo)

    except Exception as e:
        logger.exception('llm exceptiopn:')
        return
