/* SYNTHETIC generated-style code for learning. Not from any real project.
 * SWC BrakeCtrl (ASIL C), runnable BrakeCtrl_Run10ms.
 */
#include "Std_Types.h"

#define BRAKECTRL_START_SEC_VAR_ZERO_INIT_8BIT
#include "BrakeCtrl_MemMap.h"
VAR(uint8, BRAKECTRL_VAR) BrakeCtrl_BrakeRequest = 0u;
#define BRAKECTRL_STOP_SEC_VAR_ZERO_INIT_8BIT
#include "BrakeCtrl_MemMap.h"

extern uint16 SpeedMon_Speed;

#define BRAKECTRL_START_SEC_CODE
#include "BrakeCtrl_MemMap.h"
FUNC(void, BRAKECTRL_CODE) BrakeCtrl_Run10ms(void)
{
  if (SpeedMon_Speed > 100u)
  {
    BrakeCtrl_BrakeRequest = 1u;
  }
  else
  {
    BrakeCtrl_BrakeRequest = 0u;
  }
}
#define BRAKECTRL_STOP_SEC_CODE
#include "BrakeCtrl_MemMap.h"
