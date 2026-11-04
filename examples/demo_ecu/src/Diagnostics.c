/* SYNTHETIC generated-style code for learning. Not from any real project.
 * SWC Diagnostics (QM), runnable Diag_Run100ms.
 *
 * Seeded issues:
 *  - writes BrakeCtrl_BrakeRequest (ASIL C data owned by another partition)
 *  - Diag_UnmappedFlag is defined outside any MemMap section, so the linker
 *    puts it in a default section nobody has reviewed
 */
#include "Std_Types.h"

#define DIAG_START_SEC_VAR_ZERO_INIT_32BIT
#include "Diagnostics_MemMap.h"
VAR(uint32, DIAG_VAR) Diag_Counter = 0u;
#define DIAG_STOP_SEC_VAR_ZERO_INIT_32BIT
#include "Diagnostics_MemMap.h"

uint8 Diag_UnmappedFlag = 0u;

extern uint8 BrakeCtrl_BrakeRequest;

#define DIAG_START_SEC_CODE
#include "Diagnostics_MemMap.h"
FUNC(void, DIAG_CODE) Diag_Run100ms(void)
{
  Diag_Counter += 1u;
  Diag_UnmappedFlag = (uint8)(Diag_Counter == 0u);
  if (Diag_Counter > 1000u)
  {
    BrakeCtrl_BrakeRequest = 0u; /* QM code writing ASIL C data */
  }
}
#define DIAG_STOP_SEC_CODE
#include "Diagnostics_MemMap.h"
