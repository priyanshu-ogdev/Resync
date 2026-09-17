from transformers import pipeline


def build_pipeline(hf_token: str):
    return pipeline("text-generation", model="gpt2", use_auth_token=hf_token)
