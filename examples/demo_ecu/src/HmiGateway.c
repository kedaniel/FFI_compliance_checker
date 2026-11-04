/* SYNTHETIC generated-style code for learning. Not from any real project.
 * SWC HmiGateway (QM), runnable Hmi_Run20ms. It runs inside an ASIL C partition.
 *
 * Seeded issues:
 *  - writes SpeedMon_Speed (ASIL C data) from QM code
 *  - Hmi_Display (QM data) is placed in the same RAM region as ASIL C data
 */
#include "Std_Types.h"

#define HMI_START_SEC_VAR_ZERO_INIT_8BIT
#include "HmiGateway_MemMap.h"
VAR(uint8, HMI_VAR) Hmi_Display = 0u;
#define HMI_STOP_SEC_VAR_ZERO_INIT_8BIT
#include "HmiGateway_MemMap.h"

extern uint16 SpeedMon_Speed;

#define HMI_START_SEC_CODE
#include "HmiGateway_MemMap.h"
FUNC(void, HMI_CODE) Hmi_Run20ms(void)
{
  uint16 *p = &SpeedMon_Speed;   /* address taken: might be written through p */
  Hmi_Display = (uint8)(*p > 50u);
  SpeedMon_Speed = 0u;
}
#define HMI_STOP_SEC_CODE
#include "HmiGateway_MemMap.h"
