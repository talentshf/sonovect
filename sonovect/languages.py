"""Qwen3-ASR language names from the pinned Transformers 5.20.2 processor."""
QWEN_LANGUAGES = dict(zip(
    'ar yue zh cs da nl en fil fi fr de el hi hu id it ja ko mk ms fa pl pt ro ru es sv th tr vi'.split(),
    'Arabic Cantonese Chinese Czech Danish Dutch English Filipino Finnish French German Greek Hindi Hungarian Indonesian Italian Japanese Korean Macedonian Malay Persian Polish Portuguese Romanian Russian Spanish Swedish Thai Turkish Vietnamese'.split()))


def speech_language(value):
    if value is None or value.lower()=='auto':return None
    names={name.lower():code for code,name in QWEN_LANGUAGES.items()}
    code=names.get(value.lower(),value.lower().replace('_','-').split('-')[0])
    if code not in QWEN_LANGUAGES:raise ValueError('language_not_supported')
    return code
