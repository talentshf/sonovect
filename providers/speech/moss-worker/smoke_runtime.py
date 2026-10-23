"""Exercise the real MOSS audio encoder, DeepStack hooks and KV generation on tiny CPU weights."""
import torch,json
from src.modeling_moss_audio import MossAudioModel
from src.configuration_moss_audio import MossAudioConfig
from transformers import Qwen3Config
cfg=MossAudioConfig(audio_config=dict(d_model=16,output_dim=16,encoder_layers=1,encoder_attention_heads=2,encoder_ffn_dim=32,downsample_hidden_size=2,max_source_positions=16,n_window=8,deepstack_encoder_layer_indexes=[0],dropout=0.0),language_config=Qwen3Config(vocab_size=32,hidden_size=16,intermediate_size=32,num_hidden_layers=2,num_attention_heads=2,num_key_value_heads=2,head_dim=8,max_position_embeddings=128,pad_token_id=0,eos_token_id=2).to_dict(),adapter_hidden_size=32)
model=MossAudioModel(cfg).eval()
with torch.inference_mode():
 audio=torch.randn(1,128,16);features=model.audio_encoder(audio,torch.tensor([16]));n=features.last_hidden_state.shape[1]
 ids=torch.tensor([[3]*n+[4,5]])
 mask=torch.tensor([[True]*n+[False,False]])
 result=model.generate(input_ids=ids,attention_mask=torch.ones_like(ids),audio_data=audio,audio_data_seqlens=torch.tensor([16]),audio_input_mask=mask,max_new_tokens=3,do_sample=False)
 assert result.shape[-1]>ids.shape[-1]
print(json.dumps({'tiny_audio_encode_and_cached_generation':'passed','tokens':result.shape[-1]}))
