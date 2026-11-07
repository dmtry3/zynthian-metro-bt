/* Тесты без Zynthian: ядро метронома и сам плагин (.so) на имитации хоста.
 * Плагин шлёт UDP на 127.0.0.1:47801, тест слушает этот порт и считает доли. */
#include <arpa/inet.h>
#include <dlfcn.h>
#include <lv2/atom/atom.h>
#include <lv2/core/lv2.h>
#include <lv2/urid/urid.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#include "../src/metro_core.h"

static int fails = 0;
#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* ---------- ядро ---------- */
static int64_t got[64]; static int gotdown[64]; static int ngot;
static void cb(void* u, int64_t b, int d) { (void)u; if (ngot < 64) { got[ngot] = b; gotdown[ngot] = d; ngot++; } }

static void test_core(void) {
  MetroCore m;
  metro_init(&m);
  metro_set_on(&m, 1);
  ngot = 0;
  /* с позиции 0 без опережения: доля 0 сразу, потом 1,2,3 за 3.5 доли */
  for (int i = 0; i < 35; i++) metro_advance(&m, 0.1, 0.0, cb, NULL);
  CHECK(ngot == 4, "ожидал 4 доли, получил %d", ngot);
  CHECK(ngot >= 2 && got[0] == 0 && gotdown[0] == 1 && got[1] == 1 && gotdown[1] == 0, "первые доли");

  /* опережение 0.25 доли: доля 4 уходит, когда позиция ≥ 3.75 */
  ngot = 0;
  metro_advance(&m, 0.2, 0.25, cb, NULL);   /* 3.5 → 3.7 */
  CHECK(ngot == 0, "рано: %d", ngot);
  metro_advance(&m, 0.06, 0.25, cb, NULL);  /* → 3.76 */
  CHECK(ngot == 1 && got[0] == 4 && gotdown[0] == 1, "доля 4 заранее (ngot %d)", ngot);

  /* перемотка на 10.5: следующая 11, доля 10 не повторяется */
  ngot = 0;
  metro_locate(&m, 10.5, 4);
  metro_advance(&m, 0.6, 0.0, cb, NULL);
  CHECK(ngot == 1 && got[0] == 11, "после перемотки ожидал долю 11 (ngot %d, got %lld)", ngot, ngot ? (long long)got[0] : -1LL);

  /* выключен: доли не идут */
  ngot = 0;
  metro_set_on(&m, 0);
  metro_advance(&m, 4.0, 0.0, cb, NULL);
  CHECK(ngot == 0, "выключен, а доли идут: %d", ngot);
  /* включили снова в середине доли: следующая целая */
  metro_set_on(&m, 1);
  metro_advance(&m, 1.0, 0.0, cb, NULL);
  CHECK(ngot == 1, "после включения ожидал 1 долю, получил %d", ngot);

  /* размер 3/4: сильные доли 0, 3, 6 */
  metro_init(&m); metro_set_on(&m, 1); m.bpb = 3; ngot = 0;
  metro_advance(&m, 6.5, 0.0, cb, NULL);
  CHECK(ngot == 7 && gotdown[0] && !gotdown[1] && !gotdown[2] && gotdown[3] && gotdown[6], "акценты 3/4");
}

/* ---------- плагин ---------- */
static const char* uris[64]; static int nuris;
static LV2_URID map_fn(LV2_URID_Map_Handle h, const char* uri) {
  (void)h;
  for (int i = 0; i < nuris; i++) if (!strcmp(uris[i], uri)) return (LV2_URID)(i + 1);
  uris[nuris] = strdup(uri);
  return (LV2_URID)(++nuris);
}

static int recv_all(int s, int ms_total, int* beats, int* accents, int* offs, int* alive) {
  char buf[64];
  struct timeval tv = { 0, 20000 };
  setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
  for (int t = 0; t < ms_total / 20; t++) {
    ssize_t n;
    while ((n = recv(s, buf, sizeof buf - 1, 0)) > 0) {
      buf[n] = 0;
      unsigned ms, down;
      if (sscanf(buf, "beat %u %u", &ms, &down) == 2) { (*beats)++; if (down) (*accents)++; }
      else if (!strcmp(buf, "off")) (*offs)++;
      else if (!strcmp(buf, "alive")) (*alive)++;
    }
  }
  return 0;
}

static void test_plugin(const char* so) {
  void* lib = dlopen(so, RTLD_NOW);
  CHECK(lib != NULL, "dlopen %s: %s", so, dlerror());
  if (!lib) return;
  const LV2_Descriptor* (*desc_fn)(uint32_t) = (const LV2_Descriptor* (*)(uint32_t))dlsym(lib, "lv2_descriptor");
  const LV2_Descriptor* d = desc_fn(0);
  CHECK(d && !strcmp(d->URI, "urn:metrobt:metro"), "URI");

  int s = socket(AF_INET, SOCK_DGRAM, 0);
  struct sockaddr_in a = { 0 };
  a.sin_family = AF_INET; a.sin_port = htons(47801); a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  if (bind(s, (struct sockaddr*)&a, sizeof a) != 0) { printf("SKIP plugin: порт 47801 занят\n"); return; }

  LV2_URID_Map map = { NULL, map_fn };
  LV2_Feature fmap = { LV2_URID__map, &map };
  const LV2_Feature* feats[] = { &fmap, NULL };
  const double sr = 48000;
  LV2_Handle h = d->instantiate(d, sr, "", feats);
  float on = 1, accent = 1, pulse = 60, advance = 0;
  struct { LV2_Atom_Sequence seq; uint8_t pad[4096]; } in, out;
  d->connect_port(h, 0, &on); d->connect_port(h, 1, &accent);
  d->connect_port(h, 2, &pulse); d->connect_port(h, 3, &advance);
  d->connect_port(h, 4, &in); d->connect_port(h, 5, &out);
  /* пустой вход, транспорт стоит, 120 BPM по умолчанию: 2 доли в секунду. 3 с звука = доли 0..5 */
  const uint32_t n = 256;
  const int blocks = (int)(3.0 * sr / n);
  for (int i = 0; i < blocks; i++) {
    in.seq.atom.type = map_fn(NULL, LV2_ATOM__Sequence);
    in.seq.atom.size = sizeof(LV2_Atom_Sequence_Body);
    out.seq.atom.size = sizeof out.pad;
    d->run(h, n);
  }
  on = 0;
  d->run(h, n);
  int beats = 0, accents = 0, offs = 0, alive = 0;
  recv_all(s, 300, &beats, &accents, &offs, &alive);
  CHECK(beats == 6, "за 3 с при 120 BPM ожидал 6 долей, получил %d", beats);
  CHECK(accents == 2, "ожидал 2 сильные доли (0 и 4), получил %d", accents);
  CHECK(offs == 1, "ожидал off после выключения, получил %d", offs);
  CHECK(alive >= 1, "нет alive");
  d->cleanup(h);
  offs = 0;
  recv_all(s, 100, &beats, &accents, &offs, &alive);
  CHECK(offs == 1, "cleanup должен прислать off, получил %d", offs);
  close(s);
}

int main(int argc, char** argv) {
  test_core();
  if (argc > 1) test_plugin(argv[1]);
  if (fails) { printf("%d ошибок\n", fails); return 1; }
  printf("OK\n");
  return 0;
}
