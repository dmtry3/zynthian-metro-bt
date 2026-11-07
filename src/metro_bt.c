/* Metro BT: LV2 MIDI tool. Считает доли по транспорту Zynthian и отправляет их сервису metro_bt
 * (UDP 127.0.0.1), который вибрирует браслетом. MIDI проходит насквозь.
 *
 * В run(): только расчёт и запись в очередь без блокировок. Сокет и сон — в своём потоке. */
#include <lv2/core/lv2.h>
#include <lv2/atom/atom.h>
#include <lv2/atom/util.h>
#include <lv2/midi/midi.h>
#include <lv2/time/time.h>
#include <lv2/urid/urid.h>
#include <arpa/inet.h>
#include <math.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include "metro_core.h"

#define METRO_URI "urn:metrobt:metro"
#define UDP_PORT 47801
#define QSIZE 64                 /* степень двойки */
#define POLL_NS 1000000L         /* поток проверяет очередь раз в 1 мс */
#define ALIVE_EVERY 1000         /* «я в цепочке» раз в секунду (в опросах) */

/* Контроллеры идут первыми (индексы 0..P_END-1), как в generative-arp: так Zynthian нумерует порты. */
enum { P_ON = 0, P_ACCENT, P_PULSE, P_ADVANCE, P_END, P_MIDI_IN = P_END, P_MIDI_OUT };

enum { EV_BEAT = 1, EV_OFF = 2 };
typedef struct { uint8_t type, downbeat; uint16_t ms; } Ev;

typedef struct {
  const LV2_Atom_Sequence* in;
  LV2_Atom_Sequence* out;
  const float* ctl[P_END];
  LV2_URID midi_Event, atom_Object, atom_Float, atom_Double, atom_Long, atom_Int;
  LV2_URID time_Position, time_bar, time_barBeat, time_bpm, time_speed, time_bpb;
  double sr, bpm;
  int rolling, on_prev;
  MetroCore core;
  uint16_t pulse_ms;
  int accent;

  /* очередь: пишет run(), читает поток */
  Ev q[QSIZE];
  atomic_uint qw, qr;
  atomic_int quit;
  pthread_t thr;
  int thr_ok;
} Metro;

static void push(Metro* M, Ev e) {
  unsigned w = atomic_load_explicit(&M->qw, memory_order_relaxed);
  unsigned r = atomic_load_explicit(&M->qr, memory_order_acquire);
  if (w - r >= QSIZE) return;   /* переполнение: долю пропускаем, ждать нельзя */
  M->q[w & (QSIZE - 1)] = e;
  atomic_store_explicit(&M->qw, w + 1, memory_order_release);
}

static void* sender(void* arg) {
  Metro* M = (Metro*)arg;
  int s = socket(AF_INET, SOCK_DGRAM, 0);
  struct sockaddr_in a;
  memset(&a, 0, sizeof a);
  a.sin_family = AF_INET;
  a.sin_port = htons(UDP_PORT);
  a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  const struct timespec ts = { 0, POLL_NS };
  int tick = ALIVE_EVERY;
  while (!atomic_load(&M->quit)) {
    char msg[48];
    unsigned r = atomic_load_explicit(&M->qr, memory_order_relaxed);
    while (r != atomic_load_explicit(&M->qw, memory_order_acquire)) {
      Ev e = M->q[r & (QSIZE - 1)];
      atomic_store_explicit(&M->qr, ++r, memory_order_release);
      int n = e.type == EV_BEAT ? snprintf(msg, sizeof msg, "beat %u %u", e.ms, e.downbeat)
                                : snprintf(msg, sizeof msg, "off");
      if (s >= 0) sendto(s, msg, (size_t)n, 0, (struct sockaddr*)&a, sizeof a);
    }
    if (++tick >= ALIVE_EVERY) {
      tick = 0;
      if (s >= 0) sendto(s, "alive", 5, 0, (struct sockaddr*)&a, sizeof a);
    }
    nanosleep(&ts, NULL);
  }
  if (s >= 0) {
    sendto(s, "off", 3, 0, (struct sockaddr*)&a, sizeof a);
    sendto(s, "bye", 3, 0, (struct sockaddr*)&a, sizeof a);
    close(s);
  }
  return NULL;
}

static double numv(const Metro* M, const LV2_Atom* a, double def) {
  if (!a) return def;
  if (a->type == M->atom_Float)  return ((const LV2_Atom_Float*)a)->body;
  if (a->type == M->atom_Double) return ((const LV2_Atom_Double*)a)->body;
  if (a->type == M->atom_Long)   return (double)((const LV2_Atom_Long*)a)->body;
  if (a->type == M->atom_Int)    return ((const LV2_Atom_Int*)a)->body;
  return def;
}

static void on_beat(void* user, int64_t beat, int downbeat) {
  (void)beat;
  Metro* M = (Metro*)user;
  Ev e = { EV_BEAT, (uint8_t)(downbeat && M->accent), M->pulse_ms };
  push(M, e);
}

static void handle_pos(Metro* M, const LV2_Atom_Object* obj) {
  const LV2_Atom *bpm = NULL, *speed = NULL, *bb = NULL, *bar = NULL, *bpb = NULL;
  lv2_atom_object_get(obj, M->time_bpm, &bpm, M->time_speed, &speed, M->time_barBeat, &bb,
                      M->time_bar, &bar, M->time_bpb, &bpb, 0);
  if (bpm) { double v = numv(M, bpm, M->bpm); if (v >= 20 && v <= 400) M->bpm = v; }
  int nbpb = bpb ? (int)(numv(M, bpb, 4) + 0.5) : M->core.bpb;
  if (speed) {
    const int rolling = numv(M, speed, 0) != 0;
    if (rolling && !M->rolling) M->core.synced = 0;   /* пуск: первая доля сразу, если позиция на доле */
    if (!rolling && M->rolling && M->core.on) { Ev e = { EV_OFF, 0, 0 }; push(M, e); }   /* стоп: гасим вибрацию */
    M->rolling = rolling;
  }
  /* транспорт стоит: позиция замерла, долей нет */
  if (!M->rolling || !bar || !bb) { if (nbpb >= 1 && nbpb <= 32) M->core.bpb = nbpb; return; }
  metro_locate(&M->core, numv(M, bar, 0) * nbpb + numv(M, bb, 0), nbpb);
}

static void advance_frames(Metro* M, uint32_t frames) {
  if (!frames || !M->rolling) return;   /* метроном идёт только при запущенном транспорте */
  const double bps = M->bpm / 60.0;
  const double adv = (M->ctl[P_ADVANCE] ? *M->ctl[P_ADVANCE] : 50.0f) / 1000.0 * bps;
  metro_advance(&M->core, frames / M->sr * bps, adv, on_beat, M);
}

static void run(LV2_Handle h, uint32_t n) {
  Metro* M = (Metro*)h;
  const uint32_t cap = M->out->atom.size;
  lv2_atom_sequence_clear(M->out);
  M->out->atom.type = M->in->atom.type;

  const int on = M->ctl[P_ON] ? *M->ctl[P_ON] > 0.5f : 0;
  M->accent = M->ctl[P_ACCENT] ? *M->ctl[P_ACCENT] > 0.5f : 1;
  float p = M->ctl[P_PULSE] ? *M->ctl[P_PULSE] : 60.0f;
  M->pulse_ms = (uint16_t)(p < 20 ? 20 : p > 300 ? 300 : p);

  /* контроллеры меняются между блоками: переключение обрабатываем в начале блока */
  if (on != M->on_prev) {
    metro_set_on(&M->core, on);
    if (!on) { Ev e = { EV_OFF, 0, 0 }; push(M, e); }
    M->on_prev = on;
  }

  uint32_t cur = 0;
  LV2_ATOM_SEQUENCE_FOREACH(M->in, ev) {
    uint32_t f = (uint32_t)ev->time.frames;
    if (f > n) f = n;
    if (f > cur) { advance_frames(M, f - cur); cur = f; }
    if (ev->body.type == M->midi_Event) {
      lv2_atom_sequence_append_event(M->out, cap, ev);   /* MIDI насквозь */
    } else if (ev->body.type == M->atom_Object) {
      const LV2_Atom_Object* o = (const LV2_Atom_Object*)&ev->body;
      if (o->body.otype == M->time_Position) handle_pos(M, o);
    }
  }
  advance_frames(M, n - cur);
}

static LV2_Handle instantiate(const LV2_Descriptor* d, double rate, const char* path,
                              const LV2_Feature* const* f) {
  (void)d; (void)path;
  LV2_URID_Map* m = NULL;
  for (int i = 0; f[i]; i++)
    if (!strcmp(f[i]->URI, LV2_URID__map)) m = (LV2_URID_Map*)f[i]->data;
  if (!m) return NULL;
  Metro* M = (Metro*)calloc(1, sizeof(Metro));
  if (!M) return NULL;
  M->midi_Event    = m->map(m->handle, LV2_MIDI__MidiEvent);
  M->atom_Object   = m->map(m->handle, LV2_ATOM__Object);
  M->atom_Float    = m->map(m->handle, LV2_ATOM__Float);
  M->atom_Double   = m->map(m->handle, LV2_ATOM__Double);
  M->atom_Long     = m->map(m->handle, LV2_ATOM__Long);
  M->atom_Int      = m->map(m->handle, LV2_ATOM__Int);
  M->time_Position = m->map(m->handle, LV2_TIME__Position);
  M->time_bar      = m->map(m->handle, LV2_TIME__bar);
  M->time_barBeat  = m->map(m->handle, LV2_TIME__barBeat);
  M->time_bpm      = m->map(m->handle, LV2_TIME__beatsPerMinute);
  M->time_speed    = m->map(m->handle, LV2_TIME__speed);
  M->time_bpb      = m->map(m->handle, LV2_TIME__beatsPerBar);
  M->sr = rate; M->bpm = 120.0;
  metro_init(&M->core);
  atomic_init(&M->qw, 0); atomic_init(&M->qr, 0); atomic_init(&M->quit, 0);
  M->thr_ok = pthread_create(&M->thr, NULL, sender, M) == 0;
  return M;
}

static void connect_port(LV2_Handle h, uint32_t port, void* data) {
  Metro* M = (Metro*)h;
  if (port < P_END) M->ctl[port] = (const float*)data;
  else if (port == P_MIDI_IN) M->in = (const LV2_Atom_Sequence*)data;
  else if (port == P_MIDI_OUT) M->out = (LV2_Atom_Sequence*)data;
}

static void cleanup(LV2_Handle h) {
  Metro* M = (Metro*)h;
  atomic_store(&M->quit, 1);
  if (M->thr_ok) pthread_join(M->thr, NULL);
  free(M);
}

static const LV2_Descriptor descriptor = {
  METRO_URI, instantiate, connect_port, NULL, run, NULL, cleanup, NULL
};

LV2_SYMBOL_EXPORT const LV2_Descriptor* lv2_descriptor(uint32_t i) {
  return i == 0 ? &descriptor : NULL;
}
