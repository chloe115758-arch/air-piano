"""MIDI 파일을 에어 피아노가 읽는 songs.js 로 바꿔요.

곡을 더 넣으려면: midi/ 폴더에 .mid 파일을 넣고, 아래 PIECES 에 한 줄 추가한 뒤
    python3 midi2song.py
를 실행하세요. (저작권이 끝났거나 사용이 허락된 MIDI 만 넣어 주세요.)
"""
import json
import struct
from pathlib import Path

HERE = Path(__file__).parent
MUTOPIA = "Mutopia Project"
# (파일, 화면에 보일 곡 이름, 악보 출처·라이선스 표기)
PIECES = [
    ("arabesque1.mid", "아라베스크 1번 (드뷔시)", f"{MUTOPIA} · Keith OHara · Public Domain"),
    ("nocturne_op9_1.mid", "녹턴 Op.9 No.1 (쇼팽)", f"{MUTOPIA} · Benjamin D. Esham · CC BY-SA 2.5"),
    ("moonlight1.mid", "월광 소나타 1악장 (베토벤)", f"{MUTOPIA} · Stewart Holmes · CC BY-SA 2.5"),
    ("gymnopedie1.mid", "짐노페디 1번 (사티)", f"{MUTOPIA} · Evin Robertson · Public Domain"),
]


def vlq(d, i):
    n = 0
    while True:
        n = (n << 7) | (d[i] & 0x7F)
        i += 1
        if not d[i - 1] & 0x80:
            return n, i


def read(path):
    """(tick, 순서, 종류, a, b) 목록과 4분음표당 tick 수를 돌려줘요."""
    d = path.read_bytes()
    assert d[:4] == b"MThd", "MIDI 파일이 아니에요"
    hlen, _fmt, ntracks, div = struct.unpack(">IHHH", d[4:14])
    assert not div & 0x8000, "SMPTE 시간 형식은 지원하지 않아요"
    pos, out = 8 + hlen, []
    for _ in range(ntracks):
        assert d[pos:pos + 4] == b"MTrk"
        end = pos + 8 + struct.unpack(">I", d[pos + 4:pos + 8])[0]
        i, tick, status = pos + 8, 0, 0
        while i < end:
            dt, i = vlq(d, i)
            tick += dt
            if d[i] == 0xFF:  # 메타: 빠르기만 챙겨요
                kind = d[i + 1]
                n, i = vlq(d, i + 2)
                if kind == 0x51:
                    out.append((tick, 0, "tempo", int.from_bytes(d[i:i + n], "big"), 0))
                i += n
            elif d[i] in (0xF0, 0xF7):
                n, i = vlq(d, i + 1)
                i += n
            else:
                if d[i] & 0x80:
                    status = d[i]
                    i += 1
                hi = status & 0xF0
                if hi in (0xC0, 0xD0):
                    i += 1
                    continue
                a, b = d[i], d[i + 1]
                i += 2
                if hi == 0x90 and b:
                    out.append((tick, 3, "on", a, b))
                elif hi in (0x80, 0x90):
                    out.append((tick, 1, "off", a, 0))
                elif hi == 0xB0 and a == 64:  # 서스테인 페달
                    out.append((tick, 2, "pedal", b >= 64, 0))
        pos = end
    return sorted(out), div


def convert(path):
    events, div = read(path)
    ms, last_tick, tempo = 0.0, 0, 500000
    sounding, held, pedal, notes = {}, [], False, []  # notes: [시작ms, 음, 세기, 끝ms]
    for tick, _, kind, a, b in events:
        ms += (tick - last_tick) * tempo / div / 1000
        last_tick = tick
        if kind == "tempo":
            tempo = a
        elif kind == "on":
            if a in sounding:  # 같은 음을 다시 치면 앞의 음은 여기서 끝
                sounding.pop(a)[3] = ms
            sounding[a] = [ms, a, b, None]
            notes.append(sounding[a])
        elif kind == "off" and a in sounding:
            n = sounding.pop(a)
            if pedal:
                held.append(n)  # 페달을 밟고 있으면 뗄 때까지 울려요
            else:
                n[3] = ms
        elif kind == "pedal":
            pedal = a
            if not pedal:
                for n in held:
                    n[3] = ms
                held = []
    for n in notes:
        if n[3] is None:
            n[3] = ms
    start = min(n[0] for n in notes)
    by_time = {}
    for t0, midi, vel, t1 in notes:
        chord = by_time.setdefault(round(t0 - start), [])
        if all(n[0] != midi for n in chord):  # 두 손이 같은 음을 동시에 치면 한 번만
            chord.append([midi, round(vel / 127, 2), max(60, round(t1 - t0))])
    return {
        "unit": 1,
        "len": round(max(n[3] for n in notes) - start),
        "events": [{"t": t, "notes": by_time[t]} for t in sorted(by_time)],
    }


if __name__ == "__main__":
    songs = {}
    for file, title, credit in PIECES:
        song = convert(HERE / "midi" / file)
        song["credit"] = credit
        songs[title] = song
        pitches = [n[0] for e in song["events"] for n in e["notes"]]
        vols = [n[1] for e in song["events"] for n in e["notes"]]
        assert 21 <= min(pitches) and max(pitches) <= 108, "88건반 밖의 음이 있어요"
        assert all(a["t"] < b["t"] for a, b in zip(song["events"], song["events"][1:]))
        print(f"{title}: {len(pitches)}음, {song['len'] / 1000:.0f}초, 음역 {min(pitches)}~{max(pitches)}, 세기 {min(vols)}~{max(vols)}")
    text = "// midi2song.py 가 만든 파일이에요. 직접 고치지 마세요.\nexport const MIDI_SONGS = " + json.dumps(songs, ensure_ascii=False, separators=(",", ":")) + ";\n"
    (HERE / "songs.js").write_text(text, encoding="utf-8")
    print(f"songs.js 저장: {len(text) / 1024:.0f} KB")
