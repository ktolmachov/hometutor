# Local AI Runtime Notes

Финальный RAG runtime использует модель `qwopus3.6-35b-a3b-v1-mtp`.

Финальный runtime:

```text
model = qwopus3.6-35b-a3b-v1-mtp
mode = rag
ctx = 32768
launcher = Start-MoeAutoFit-LlamaCpp-v1.ps1
entrypoint = Start-LocalModel.ps1 v5.2.4
```

Финальный startup status:

```text
WAIT_LLAMA_READY_V1_1=PASS
START_LOCAL_MODEL_READINESS_GATE=PASS
START_LOCAL_MODEL_SMOKE=PASS
START_LOCAL_MODEL=PASS
```

Профили:

```text
rag:
  ctx = 32768
  purpose = long-doc / quality RAG
  status = PREFILL_DECODE_DIAGNOSTIC_V2_1_PASS
  readiness = 24k context probe

rag-fast:
  ctx = 16384
  purpose = quick Q&A / tutor / medium context
  status = PREFILL_DECODE_DIAGNOSTIC_V2_1_PASS_WITH_EXPECTED_SKIPS
  readiness = 12k context probe
```

Главный инженерный вывод: модель, которая отвечает, — это демка. Модель, которая проходит gates, — это runtime.
