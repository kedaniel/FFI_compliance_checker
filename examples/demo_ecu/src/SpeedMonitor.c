/* SYNTHETIC generated-style code for learning. Not from any real project.
 * SWC SpeedMonitor (ASIL C), runnable SpeedMon_Run5ms.
 */
#include "Std_Types.h"

#define SPEEDMON_START_SEC_VAR_ZERO_INIT_16BIT
#include "SpeedMonitor_MemMap.h"
VAR(uint16, SPEEDMON_VAR) SpeedMon_Speed = 0u;
#define SPEEDMON_STOP_SEC_VAR_ZERO_INIT_16BIT
#include "SpeedMonitor_MemMap.h"

extern uint8 Hmi_Display;

#define SPEEDMON_START_SEC_CODE
#include "SpeedMonitor_MemMap.h"
FUNC(void, SPEEDMON_CODE) SpeedMon_Run5ms(void)
{
  /* Reads another SWC's data (a read is not an interference by itself) */
  if (Hmi_Display == 0u)
  {
    SpeedMon_Speed++;
  }
}
#define SPEEDMON_STOP_SEC_CODE
#include "SpeedMonitor_MemMap.h"
