"""
Observability and analytics facade for the application.
Decomposed into modular submodules. 
Uses a Custom Module Class to support dynamic patching of constants in tests 
(via module-level __setattr__) and ensure reliable state reset during reloads.
"""

from __future__ import annotations

import importlib
import sys
import types
from typing import Any

# Ensure submodules are loaded
import app.metrics_core
import app.metrics_storage
import app.metrics_aggregator
import app.metrics_graph_expansion
import app.metrics_summarizer
import app.metrics_db

class MetricsModule(types.ModuleType):
    """
    A custom module class that allows intercepting attribute access and assignment.
    This is used to proxy constants to app.metrics_core and functions to submodules.
    """
    def __getattr__(self, name: str) -> Any:
        # Proxy constants from metrics_core
        if name in ("METRICS_STORE_PATH", "METRICS_DASHBOARD_DB_PATH", 
                    "METRICS_STORE_SCHEMA_VERSION", "PIPELINE_TRACE_SCHEMA_VERSION", 
                    "RETRIEVAL_TRACE_SCHEMA_VERSION"):
            return getattr(sys.modules["app.metrics_core"], name)
        
        # Proxy functions from submodules
        # metrics_core
        if name in ("check_pipeline_trace_schema", "check_metrics_store_line_schema", "check_retrieval_trace_schema"):
            return getattr(sys.modules["app.metrics_core"], name)
        
        # metrics_storage
        if name in ("get_metrics_store", "record_quality_judge", "record_knowledge_workflow_event", "record_ingestion_run"):
            return getattr(sys.modules["app.metrics_storage"], name)
            
        # metrics_aggregator
        if name in ("record_request", "record_error", "get_metrics"):
            return getattr(sys.modules["app.metrics_aggregator"], name)
            
        # metrics_graph_expansion
        if name in ("compact_graph_expansion_for_metrics", "aggregate_graph_expansion_from_request_events"):
            return getattr(sys.modules["app.metrics_graph_expansion"], name)
            
        # metrics_summarizer
        if name in ("summarize_metrics_store", "get_cost_dashboard", "get_quality_metrics", 
                    "get_knowledge_workflow_metrics", "collect_latency_by_query_mode",
                    "evaluate_slo_alerts", "evaluate_slo_alerts_and_notify"):
            return getattr(sys.modules["app.metrics_summarizer"], name)
            
        # metrics_db
        if name in ("get_metrics_dashboard",):
            return getattr(sys.modules["app.metrics_db"], name)
            
        raise AttributeError(f"module {__name__} has no attribute {name}")

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "METRICS_STORE_PATH":
            import app.metrics_core
            app.metrics_core.METRICS_STORE_PATH = value
            types.ModuleType.__setattr__(self, name, value)
        elif name == "METRICS_DASHBOARD_DB_PATH":
            import app.metrics_core
            app.metrics_core.METRICS_DASHBOARD_DB_PATH = value
            types.ModuleType.__setattr__(self, name, value)
        else:
            super().__setattr__(name, value)

# The magic: change the class of the current module instance to our custom class.
# This keeps the same object ID in sys.modules so importlib.reload works,
# but gives us __getattr__ and __setattr__ behavior for the module.
sys.modules[__name__].__class__ = MetricsModule

# Internal reload logic to be called on every module execution (including reloads)
def _reload_all():
    importlib.reload(app.metrics_core)
    importlib.reload(app.metrics_graph_expansion)
    importlib.reload(app.metrics_storage)
    importlib.reload(app.metrics_aggregator)
    importlib.reload(app.metrics_summarizer)
    importlib.reload(app.metrics_db)

_reload_all()

# Mirror path constants into the module namespace so unittest.mock.patch.object
# treats them as real module attributes (local=True → setattr restore on exit).
_m = sys.modules[__name__]
for _name in ("METRICS_STORE_PATH", "METRICS_DASHBOARD_DB_PATH"):
    types.ModuleType.__setattr__(_m, _name, getattr(sys.modules["app.metrics_core"], _name))
