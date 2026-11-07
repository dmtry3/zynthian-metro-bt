/* Ядро метронома без LV2: решает, когда отправить долю на браслет.
 * Время в долях (beat). Долю отправляем заранее на advance долей, чтобы компенсировать задержку Bluetooth. */
#ifndef METRO_CORE_H
#define METRO_CORE_H

#include <stdint.h>

#define METRO_JUMP_BEATS 0.25   /* скачок позиции больше этого = перемотка */

typedef struct {
  double pos;        /* текущая позиция в долях: bar*bpb + barBeat (или свои часы, если транспорт стоит) */
  int64_t next;      /* номер следующей доли, которую надо отправить */
  int bpb;           /* долей в такте */
  int on;
  int synced;        /* next посчитан для текущей позиции */
} MetroCore;

/* beat: номер доли (для акцента: beat % bpb == 0 — сильная доля) */
typedef void (*metro_beat_fn)(void* user, int64_t beat, int downbeat);

void metro_init(MetroCore* m);
void metro_set_on(MetroCore* m, int on);
/* Хост сообщил позицию (транспорт идёт). Скачок = перемотка: заново ищем следующую долю. */
void metro_locate(MetroCore* m, double pos, int bpb);
/* Продвинуться на beats долей; доли, чьё время отправки (доля - advance) наступило, уходят в fn. */
void metro_advance(MetroCore* m, double beats, double advance, metro_beat_fn fn, void* user);

#endif
