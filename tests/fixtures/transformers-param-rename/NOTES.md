# transformers-param-rename

Real, verified change (see `src/resync/knowledge/seed_data.py`): Hugging Face `transformers` PR #25083
renamed the `use_auth_token` keyword argument to `token` across `.from_pretrained()` methods.

- From: any version before 4.32.0
- To: 4.32.0 and later
- Correct fix: rename the keyword argument at each call site; no other logic changes.
