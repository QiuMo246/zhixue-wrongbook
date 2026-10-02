"""
宣传片拟音合成 —— 零依赖素材，代码生成 wav。
用法：python gen_sfx.py
输出：promo-video/public/sfx/*.wav

设计原则（对应画面的「红笔订正·错题本」纸质手作感）：
- 纸质类拟音（卡片拍落、纸页翻动）用短噪声 + 快速衰减
- 红笔盖章用低频冲击 + 一点点金属泛音，模仿按压印章
- 荧光笔划线用窄带噪声扫频，模拟笔尖摩擦
- 气泡/徽章弹出用短促正弦点击，音高略上行
全部做峰值归一化到 -3 dBFS，避免爆音。
"""
import os
import numpy as np

SR = 44100
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", "sfx")
os.makedirs(OUT, exist_ok=True)

rng = np.random.default_rng(20260930)


def env(n, attack=0.005, decay=0.25, power=2.0):
    """指数衰减包络：attack 秒起音，其余按 power 次幂衰减"""
    a = max(1, int(attack * SR))
    t = np.arange(n) / SR
    e = np.exp(-t / max(decay, 1e-4)) ** power
    e[:a] = np.linspace(0, 1, a) ** 0.6
    return e


def noise(n):
    return rng.uniform(-1, 1, n)


def tone(n, f0, f1=None, shape="sine"):
    """从 f0 线性滑到 f1 的振荡器（f1 缺省则恒定）"""
    f1 = f0 if f1 is None else f1
    phase = np.cumsum(np.linspace(0, 1, n) * (f0 + f1) / 2 * 2 * np.pi)
    if shape == "sine":
        return np.sin(phase)
    if shape == "tri":
        return 2 / np.pi * np.arcsin(np.sin(phase))
    return np.sign(np.sin(phase))


def lowpass(x, cutoff):
    """一阶低通，cutoff 归一化到 (0,1)"""
    a = np.clip(cutoff, 0.001, 0.99)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += a * (x[i] - acc)
        y[i] = acc
    return y


def highpass(x, cutoff):
    return x - lowpass(x, cutoff)


def bandpass(x, lo, hi):
    return lowpass(highpass(x, lo), hi)


def norm(x, peak_db=-3.0):
    m = np.max(np.abs(x))
    if m < 1e-9:
        return x
    return x / m * (10 ** (peak_db / 20))


def save(name, x, peak_db=-3.0):
    x = norm(x, peak_db)
    # 首尾各 5ms 淡入淡出，消除咔哒声
    f = int(0.005 * SR)
    if len(x) > f * 2:
        x[:f] *= np.linspace(0, 1, f)
        x[-f:] *= np.linspace(1, 0, f)
    x = np.clip(x, -1.0, 1.0)
    p = os.path.join(OUT, name + ".wav")
    # 16-bit PCM
    with open(p, "wb") as fh:
        import wave

        w = wave.open(fh, "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())
        w.close()
    print(f"  {name:<16} {len(x)/SR*1000:6.0f} ms  peak {20*np.log10(np.max(np.abs(x))+1e-9):.1f} dBFS")


# ---------- 1. 纸卡片拍落（低频闷响 + 纸张摩擦）----------
def card_drop():
    n = int(0.28 * SR)
    thud = tone(n, 150, 60) * env(n, 0.002, 0.05, 2.2)
    paper = bandpass(noise(n), 0.25, 0.75) * env(n, 0.001, 0.045, 3.0) * 0.5
    return thud * 0.8 + paper


# ---------- 2. 红笔盖章（干脆的按压冲击 + 轻微泛音）----------
def stamp():
    n = int(0.22 * SR)
    body = tone(n, 320, 90) * env(n, 0.001, 0.035, 2.6)
    click = bandpass(noise(n), 0.5, 0.9) * env(n, 0.0005, 0.012, 4.0) * 0.55
    ring = tone(n, 1150, 1050) * env(n, 0.001, 0.03, 3.5) * 0.18
    return body + click + ring


# ---------- 3. 荧光笔划线（笔尖摩擦，窄带噪声上扫）----------
def highlighter(dur=0.42):
    n = int(dur * SR)
    t = np.arange(n) / SR
    nz = noise(n)
    # 用时变截止频率模拟笔尖划过的频谱变化
    y = np.zeros(n)
    for i in range(n):
        cut = 0.18 + 0.5 * (i / n)
        y[i] = nz[i] * cut
    y = lowpass(y, 0.6)
    y = highpass(y, 0.05)
    e = np.sin(np.linspace(0, np.pi, n)) ** 0.7  # 中段最响，两头收
    return y * e * 0.9


# ---------- 4. 气泡/徽章弹出（短促点击，音高略上行）----------
def pop(f0=520, dur=0.1):
    n = int(dur * SR)
    return tone(n, f0, f0 * 1.6) * env(n, 0.002, 0.028, 2.4)


# ---------- 4b. 芯片/贴纸落位（短促高频，区别于纸质低闷）----------
def chip(dur=0.06):
    n = int(dur * SR)
    t = tone(n, 1700, 1250) * env(n, 0.0008, 0.013, 3.2)
    k = bandpass(noise(n), 0.6, 0.95) * env(n, 0.0004, 0.006, 4.5) * 0.5
    return t * 0.6 + k


# ---------- 4c. 金属转轴（转场用，带金属泛音）----------
def metal_click(dur=0.16):
    n = int(dur * SR)
    body = tone(n, 880, 700) * env(n, 0.0008, 0.022, 3.0)
    # 三个非谐波泛音 → 金属感
    metal = sum(
        tone(n, f, f * 0.985) * env(n, 0.0006, 0.03 + i * 0.012, 3.2) * a
        for i, (f, a) in enumerate([(1870, 0.28), (2640, 0.18), (3910, 0.1)])
    )
    click = bandpass(noise(n), 0.55, 0.95) * env(n, 0.0003, 0.005, 5.0) * 0.4
    return body * 0.5 + metal + click


# ---------- 4d. 铅笔落笔（写字的沙沙声）----------
def pencil(dur=0.2):
    n = int(dur * SR)
    y = bandpass(noise(n), 0.2, 0.7)
    t = np.arange(n) / SR
    # 笔尖摩擦的颗粒感：叠加轻微颤动
    y *= 1 + 0.35 * np.sin(2 * np.pi * 34 * t)
    e = np.sin(np.linspace(0, np.pi, n)) ** 0.8
    return y * e


# ---------- 4e. 磁性吸附（物体被吸过去的 whoosh，短而收得快）----------
def snap(dur=0.2):
    n = int(dur * SR)
    nz = noise(n)
    y = np.zeros(n)
    for i in range(n):
        y[i] = nz[i] * (0.1 + 0.6 * (i / n))
    y = bandpass(y, 0.15, 0.7)
    e = np.exp(-np.arange(n) / SR / 0.05)
    return y * e


# ---------- 4f. 铃铛（结尾用，明亮）----------
def bell(dur=0.9):
    n = int(dur * SR)
    out = np.zeros(n)
    # 非谐波分音 + 各自衰减 → 真实铃感
    for f, a, dec in [(1046, 0.5, 0.42), (1568, 0.3, 0.3), (2093, 0.2, 0.22), (3136, 0.12, 0.15)]:
        out += tone(n, f, f) * env(n, 0.002, dec, 1.6) * a
    return out


# ---------- 4g. 程序化提示（每个字符音高不同 → 像进度在走）----------
def blip(f0, dur=0.07):
    n = int(dur * SR)
    return tone(n, f0, f0) * env(n, 0.002, 0.02, 2.4)


# ---------- 4h. 纸张翻页的"啪"（比 page_turn 更短促）----------
def paper_flip(dur=0.14):
    n = int(dur * SR)
    y = bandpass(noise(n), 0.35, 0.85)
    e = np.exp(-np.arange(n) / SR / 0.03)
    return y * e


# ---------- 5. 打字机轻击 ----------
def type_tick():
    n = int(0.055 * SR)
    t = tone(n, 900, 500) * env(n, 0.001, 0.014, 3.0)
    k = bandpass(noise(n), 0.4, 0.85) * env(n, 0.0005, 0.008, 4.0) * 0.4
    return t * 0.7 + k


# ---------- 6. 数字/进度推进（上扬的提示音）----------
def chime_up(dur=0.3):
    n = int(dur * SR)
    base = tone(n, 660, 990) * env(n, 0.004, 0.1, 2.0)
    harm = tone(n, 1320, 1980) * env(n, 0.004, 0.07, 2.6) * 0.3
    return base * 0.75 + harm


# ---------- 7. 成功确认（双音上行）----------
def success():
    n = int(0.42 * SR)
    a = tone(n, 784, 784) * env(n, 0.003, 0.12, 2.0)
    b = tone(n, 1046, 1046) * env(n, 0.003, 0.14, 2.0)
    # 后一个音延后 70ms 进入
    b = np.concatenate([np.zeros(int(0.07 * SR)), b])[:n] if n > int(0.07 * SR) else b
    a = np.pad(a, (0, max(0, n - len(a))))[:n]
    b = np.pad(b, (0, max(0, n - len(b))))[:n]
    return a * 0.6 + b * 0.7


# ---------- 8. 转场 whoosh（空气感掠过）----------
def whoosh(dur=0.35):
    n = int(dur * SR)
    nz = noise(n)
    y = np.zeros(n)
    for i in range(n):
        cut = 0.05 + 0.55 * (1 - abs(2 * i / n - 1))
        y[i] = nz[i] * cut
    y = bandpass(y, 0.08, 0.65)
    e = np.sin(np.linspace(0, np.pi, n)) ** 1.4
    return y * e


# ---------- 9. 纸页翻动（长一点的纸张摩擦）----------
def page_turn(dur=0.3):
    n = int(dur * SR)
    y = bandpass(noise(n), 0.3, 0.8)
    t = np.arange(n) / SR
    e = np.exp(-t / 0.13) * (1 - np.exp(-t / 0.004))
    return y * e


if __name__ == "__main__":
    print("生成拟音 →", OUT)
    save("card_drop", card_drop())
    save("stamp", stamp())
    save("highlighter", highlighter())
    save("pop_low", pop(430))
    save("pop_mid", pop(560))
    save("pop_high", pop(700))
    save("type_tick", type_tick())
    save("chime_up", chime_up())
    save("success", success())
    save("whoosh", whoosh())
    save("whoosh_soft", whoosh(0.28) * 0.7)
    save("page_turn", page_turn())
    # 扩充音色：让不同元素类型用不同声音，避免听感重复
    save("chip", chip())
    save("metal_click", metal_click())
    save("pencil", pencil())
    save("snap", snap())
    save("bell", bell())
    save("paper_flip", paper_flip())
    # 连续音高的 blip，用于「程序化逐条推进」
    for i, f in enumerate([523, 587, 659, 698, 784, 880]):
        save(f"blip{i}", blip(f))
    print("完成", len(os.listdir(OUT)), "个文件")