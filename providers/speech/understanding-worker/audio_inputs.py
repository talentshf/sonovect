"""Audio-only frontend for the pinned Transformers Qwen2.5-Omni Thinker.

Uses the upstream tokenizer/template and Whisper feature extractor. The audio
length reduction follows Qwen2_5OmniProcessor in Transformers 5.20.2 (Apache-2.0).
No image/video processors or speech generation components are needed.
"""
import json
from pathlib import Path
from transformers import AutoTokenizer,WhisperFeatureExtractor


class AudioInputs:
    def __init__(self,root):
        self.tokenizer=AutoTokenizer.from_pretrained(root,local_files_only=True,trust_remote_code=False)
        self.extractor=WhisperFeatureExtractor.from_pretrained(root,local_files_only=True)
        self.template=json.loads((Path(root)/'chat_template.json').read_text())['chat_template']

    def encode(self,audio,conversation):
        features=self.extractor([audio],sampling_rate=16000,padding='max_length',max_length=len(audio)+400,truncation=False,
            return_attention_mask=True,return_tensors='pt')
        mask=features.pop('attention_mask')
        lengths=((mask.sum(-1)-1)//2+1-2)//2+1
        text=self.tokenizer.apply_chat_template(conversation,chat_template=self.template,add_generation_prompt=True,tokenize=False)
        token=self.tokenizer.audio_token
        if text.count(token)!=1:raise ValueError('exactly_one_audio_placeholder_required')
        text=text.replace(token,token*int(lengths[0]),1)
        text_inputs=self.tokenizer([text],padding=True,return_tensors='pt')
        return {**text_inputs,**features,'feature_attention_mask':mask}
