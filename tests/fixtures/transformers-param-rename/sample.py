from transformers import AutoModel, AutoTokenizer


def load(model_name: str, hf_token: str):
    model = AutoModel.from_pretrained(model_name, use_auth_token=hf_token)
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        use_auth_token=hf_token,
        trust_remote_code=True,
    )
    return model, tokenizer
