"""Ekran kartı (GPU) testleri - OpenGL 3.3 (moderngl) ile ekran dışı (offscreen) çizim.

Testler ayrı bir süreçte çalışır; böylece bir sürücü hatası ana uygulamayı çökertmez.
GPU / OpenGL bulunamazsa testler 0 puan alır ve hata mesajı döner.
"""

import multiprocessing
import queue
import sys
import time

W, H = 1920, 1080
SOFTWARE_HINTS = ("llvmpipe", "softpipe", "swiftshader", "software", "basic render", "gdi generic", "swrast")

FULLSCREEN_VS = """
#version 330
out vec2 uv;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    uv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""

ALU_ITERS = 256
ALU_FS = """
#version 330
in vec2 uv;
uniform float t;
out vec4 color;
void main() {
    vec2 c = vec2(-0.745 + 0.0002 * sin(t), 0.186) + (uv - 0.5) * vec2(0.02, 0.012);
    vec2 z = vec2(0.0);
    float acc = 0.0;
    for (int i = 0; i < %d; i++) {
        z = clamp(vec2(z.x * z.x - z.y * z.y, 2.0 * z.x * z.y) + c, -2.0, 2.0);
        acc += dot(z, z);
    }
    color = vec4(fract(acc * 0.01), z, 1.0) * 0.001;
}
""" % ALU_ITERS

FILL_FS = """
#version 330
in vec2 uv;
uniform float t;
out vec4 color;
void main() { color = vec4(uv, t * 0.001, 0.02); }
"""

TEX_TAPS = 16
TEX_FS = """
#version 330
in vec2 uv;
uniform float t;
uniform sampler2D tex;
out vec4 color;
void main() {
    vec4 s = vec4(0.0);
    for (int i = 0; i < %d; i++) {
        vec2 o = vec2(float(i) * 0.0731 + t * 0.013, float(i * i) * 0.0117);
        s += texture(tex, uv * vec2(1.0, 0.5625) + o);
    }
    color = s / %d.0 * 0.001;
}
""" % (TEX_TAPS, TEX_TAPS)

GEO_VS = """
#version 330
in vec2 pos;
uniform float t;
out float shade;
void main() {
    float inst = float(gl_InstanceID);
    vec3 p = vec3(pos * 1.8 - 0.9, 0.0);
    p.z = 0.15 * sin(p.x * 9.0 + t + inst) * cos(p.y * 7.0 - t);
    float a = t * 0.3 + inst * 0.7;
    p.xz = mat2(cos(a), -sin(a), sin(a), cos(a)) * p.xz;
    shade = 0.5 + p.z;
    gl_Position = vec4(p.x, p.y, p.z * 0.5 + 0.5, 1.0);
}
"""
GEO_FS = """
#version 330
in float shade;
out vec4 color;
void main() { color = vec4(shade, 0.4, 1.0 - shade, 1.0); }
"""
GRID = 512        # 512x512 köşe -> ~522 bin üçgen
GEO_INSTANCES = 4


def _create_context():
    import moderngl
    attempts = [{}]
    if sys.platform.startswith("linux"):
        attempts.append({"backend": "egl"})
    errors = []
    for kw in attempts:
        try:
            return moderngl.create_standalone_context(require=330, **kw)
        except Exception as e:
            errors.append(str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__)
    raise RuntimeError("; ".join(errors))


def _measure(ctx, draw, work, budget):
    """draw() çağrısını budget saniye çalıştırır; saniyedeki iş miktarını döndürür."""
    draw(0)  # ilk çizim shader derleme / yükleme içerir, ölçüme katılmaz
    ctx.finish()
    t0 = time.perf_counter()
    for i in range(3):
        draw(i)
    ctx.finish()
    one = max((time.perf_counter() - t0) / 3, 1e-5)
    batch = max(1, min(64, int(0.05 / one)))  # bir grup ~50 ms sürsün
    n = 0
    start = time.perf_counter()
    deadline = start + budget
    while True:
        for _ in range(batch):
            n += 1
            draw(n)
        ctx.finish()
        now = time.perf_counter()
        if now >= deadline:
            return n * work / (now - start)


def _worker(budget):
    try:
        import moderngl
    except ImportError:
        return {"error": "moderngl kurulu değil (pip install moderngl)"}
    try:
        ctx = _create_context()
    except Exception as e:
        return {"error": f"OpenGL 3.3 bağlamı oluşturulamadı: {e}"}

    try:
        renderer = ctx.info.get("GL_RENDERER", "?")
        res = {"renderer": renderer, "gl_version": ctx.info.get("GL_VERSION", "?"),
               "software": any(h in renderer.lower() for h in SOFTWARE_HINTS)}
        color = ctx.texture((W, H), 4)
        depth = ctx.depth_renderbuffer((W, H))
        fbo = ctx.framebuffer([color], depth)
        fbo.use()
        ctx.viewport = (0, 0, W, H)
        pixels = W * H

        # Karıştırma (blending) açık: aksi halde döşeme tabanlı GPU'lar (Apple, mobil) üst üste
        # binen opak çizimlerde sadece son pikseli hesaplar ve sonuç gerçek dışı yüksek çıkar.
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE, moderngl.ONE

        # 1) Shader işlem gücü (ALU)
        prog = ctx.program(vertex_shader=FULLSCREEN_VS, fragment_shader=ALU_FS)
        vao = ctx.vertex_array(prog, [])

        def alu(i):
            prog["t"].value = i * 0.01
            vao.render(moderngl.TRIANGLES, vertices=3)
        _measure(ctx, alu, 0, 1.0)  # ısınma: GPU saat hızını yükseltsin
        rate = _measure(ctx, alu, pixels * ALU_ITERS / 1e9, budget)
        res["gpu_alu"] = rate
        res["fps_1080p"] = rate * 1e9 / (pixels * ALU_ITERS)

        # 2) Doldurma hızı (fill rate) - karıştırmalı tam ekran çizimler
        prog = ctx.program(vertex_shader=FULLSCREEN_VS, fragment_shader=FILL_FS)
        vao = ctx.vertex_array(prog, [])

        def fill(i):
            prog["t"].value = float(i)
            vao.render(moderngl.TRIANGLES, vertices=3, instances=8)
        res["gpu_fill"] = _measure(ctx, fill, pixels * 8 / 1e9, budget)

        # 3) Doku örnekleme (texture) - 2048x2048 mipmap'li doku, trilinear filtre
        import random
        tex = ctx.texture((2048, 2048), 4, random.Random(21).randbytes(2048 * 2048 * 4))
        tex.repeat_x = tex.repeat_y = True
        tex.build_mipmaps()
        tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        tex.use(0)
        prog = ctx.program(vertex_shader=FULLSCREEN_VS, fragment_shader=TEX_FS)
        prog["tex"].value = 0
        vao = ctx.vertex_array(prog, [])

        def texture(i):
            prog["t"].value = i * 0.37
            vao.render(moderngl.TRIANGLES, vertices=3)
        res["gpu_texture"] = _measure(ctx, texture, pixels * TEX_TAPS / 1e9, budget)

        # 4) Geometri - ~2 milyon üçgen / kare, derinlik testi açık
        import array
        verts = array.array("f")
        for y in range(GRID):
            for x in range(GRID):
                verts.extend((x / (GRID - 1), y / (GRID - 1)))
        idx = array.array("I")
        for y in range(GRID - 1):
            for x in range(GRID - 1):
                a = y * GRID + x
                idx.extend((a, a + 1, a + GRID, a + 1, a + GRID + 1, a + GRID))
        tris = len(idx) // 3 * GEO_INSTANCES
        prog = ctx.program(vertex_shader=GEO_VS, fragment_shader=GEO_FS)
        vao = ctx.vertex_array(prog, [(ctx.buffer(verts.tobytes()), "2f", "pos")],
                               index_buffer=ctx.buffer(idx.tobytes()), index_element_size=4)
        ctx.disable(moderngl.BLEND)
        ctx.enable(moderngl.DEPTH_TEST)

        def geometry(i):
            fbo.clear(depth=1.0)
            prog["t"].value = i * 0.05
            vao.render(moderngl.TRIANGLES, instances=GEO_INSTANCES)
        res["gpu_geometry"] = _measure(ctx, geometry, tris / 1e6, budget)
        return res
    except Exception as e:
        return {"error": f"GPU testi başarısız: {e}"}
    finally:
        ctx.release()


def _proc_main(budget, q):
    q.put(_worker(budget))


def gpu_all(budget, timeout=150):
    """GPU testlerini ayrı bir süreçte çalıştırır; çökme veya donmaya karşı korumalıdır."""
    mp = multiprocessing.get_context("spawn")
    q = mp.Queue()
    proc = mp.Process(target=_proc_main, args=(budget, q), daemon=True)
    proc.start()
    deadline = time.time() + timeout
    try:
        while True:
            try:
                return q.get(timeout=0.5)
            except queue.Empty:
                if not proc.is_alive():
                    try:
                        return q.get(timeout=1)
                    except queue.Empty:
                        return {"error": f"GPU süreci beklenmedik şekilde kapandı (kod {proc.exitcode})"}
                if time.time() > deadline:
                    return {"error": "GPU testi zaman aşımına uğradı"}
    finally:
        if proc.is_alive():
            proc.join(3)
        if proc.is_alive():
            proc.terminate()
