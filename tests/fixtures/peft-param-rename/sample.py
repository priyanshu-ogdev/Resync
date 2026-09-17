from peft.utils.integrations import gather_params_ctx


def load_full_state_dict(model, adapter_name: str):
    with gather_params_ctx(module=model):
        return {k: v.detach().clone() for k, v in model.named_parameters()}
