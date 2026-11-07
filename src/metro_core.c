#include "metro_core.h"

#include <math.h>
#include <string.h>

void metro_init(MetroCore* m) {
  memset(m, 0, sizeof *m);
  m->bpb = 4;
}

void metro_set_on(MetroCore* m, int on) {
  on = on != 0;
  if (on && !m->on) m->synced = 0;   /* включили: первая доля сразу, если позиция на доле */
  m->on = on;
}

void metro_locate(MetroCore* m, double pos, int bpb) {
  if (bpb >= 1 && bpb <= 32) m->bpb = bpb;
  if (fabs(pos - m->pos) > METRO_JUMP_BEATS) m->synced = 0;
  m->pos = pos;
}

void metro_advance(MetroCore* m, double beats, double advance, metro_beat_fn fn, void* user) {
  if (!m->synced) {
    /* доля в текущей позиции или следующая; если её время отправки уже прошло, уйдёт сразу */
    m->next = (int64_t)ceil(m->pos - 1e-6);
    m->synced = 1;
  }
  const double end = m->pos + (beats > 0 ? beats : 0);
  while ((double)m->next - advance <= end) {
    if (m->on) {
      int64_t r = m->next % m->bpb;
      if (r < 0) r += m->bpb;
      fn(user, m->next, r == 0);
    }
    m->next++;
  }
  m->pos = end;
}
