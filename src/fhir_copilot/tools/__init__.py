"""5 個唯讀工具(PLAN.md M2):get_patient_demographics、list_active_conditions、
list_active_medications、get_recent_observations、get_care_plan_timeline。

每個工具回傳值皆附 evidence(FHIR resourceType/id),查無病患時回傳結構化
ToolErrorCode.PATIENT_NOT_FOUND(不是空 list 混過去)。
"""

from fhir_copilot.tools.base import Evidence, ToolErrorCode
from fhir_copilot.tools.careplan import (
    CarePlanSummary,
    GetCarePlanTimelineInput,
    GetCarePlanTimelineResult,
    get_care_plan_timeline,
)
from fhir_copilot.tools.conditions import (
    ConditionSummary,
    ListActiveConditionsInput,
    ListActiveConditionsResult,
    list_active_conditions,
)
from fhir_copilot.tools.demographics import (
    GetPatientDemographicsInput,
    GetPatientDemographicsResult,
    PatientDemographics,
    get_patient_demographics,
)
from fhir_copilot.tools.medications import (
    ListActiveMedicationsInput,
    ListActiveMedicationsResult,
    MedicationSummary,
    list_active_medications,
)
from fhir_copilot.tools.observations import (
    GetRecentObservationsInput,
    GetRecentObservationsResult,
    ObservationSummary,
    get_recent_observations,
)
from fhir_copilot.tools.registry import READ_ONLY_TOOLS, TOOLS_BY_NAME, ToolSpec, llm_facing_schema

__all__ = [
    "READ_ONLY_TOOLS",
    "TOOLS_BY_NAME",
    "CarePlanSummary",
    "ConditionSummary",
    "Evidence",
    "GetCarePlanTimelineInput",
    "GetCarePlanTimelineResult",
    "GetPatientDemographicsInput",
    "GetPatientDemographicsResult",
    "GetRecentObservationsInput",
    "GetRecentObservationsResult",
    "ListActiveConditionsInput",
    "ListActiveConditionsResult",
    "ListActiveMedicationsInput",
    "ListActiveMedicationsResult",
    "MedicationSummary",
    "ObservationSummary",
    "PatientDemographics",
    "ToolErrorCode",
    "ToolSpec",
    "get_care_plan_timeline",
    "get_patient_demographics",
    "get_recent_observations",
    "list_active_conditions",
    "list_active_medications",
    "llm_facing_schema",
]
