from typing import NamedTuple, Optional
import asyncio
from playwright.async_api import Error as PwError, TimeoutError as PwTimeout
from playwright._impl._errors import Error as PWError


class KeyMapping(NamedTuple):
    """Class for keys and modifiers return."""

    modifiers: list[str]
    keys: list[str]

def keys_mapping(xdotool_command: str):
    # Handle splitting and stripping leading/trailing whitespace
    key_parts = [part.strip().lower() for part in xdotool_command.split("+")]

    # Dictionary mapping xdotool keys to Selenium Keys constants
    key_mapping = {
        "ctrl": "Control",
        "control": "Control",
        "alt": "Alt",
        "shift": "Shift",
        "super": "Meta",
        "command": "Meta",
        "meta": "Meta",
        "win": "Meta",
        "cmd":"Meta",
        "cancel": "Cancel",
        "help": "Help",
        "backspace": "Backspace",
        "back_space": "Backspace",
        "tab": "Tab",
        "clear": "Clear",
        "return": "Enter",
        "enter": "Enter",
        "pause": "Pause",
        "escape": "Escape",
        "esc":"Escape",
        "space": "Space",
        "pageup": "PageUp",
        "page_up": "PageUp",
        "pgup":"PageUp",
        "pagedown": "PageDown",
        "page_down": "PageDown",
        "pgdn":"PageDown",
        "end": "End",
        "home": "Home",
        "left": "ArrowLeft",
        "arrowleft": "ArrowLeft",
        "arrow_left": "ArrowLeft",
        "up": "ArrowUp",
        "arrowup": "ArrowUp",
        "arrow_up": "ArrowUp",
        "right": "ArrowRight",
        "arrowright": "ArrowRight",
        "arrow_right": "ArrowRight",
        "down": "ArrowDown",
        "arrowdown": "ArrowDown",
        "arrow_down": "ArrowDown",
        "insert": "Insert",
        "delete": "Delete",
        "semicolon": ";",
        "equals": "=",
        "kp_0": "Numpad0",
        "kp_1": "Numpad1",
        "kp_2": "Numpad2",
        "kp_3": "Numpad3",
        "kp_4": "Numpad4",
        "kp_5": "Numpad5",
        "kp_6": "Numpad6",
        "kp_7": "Numpad7",
        "kp_8": "Numpad8",
        "kp_9": "Numpad9",
        "multiply": "NumpadMultiply",
        "add": "NumpadAdd",
        "separator": "NumpadComma",
        "subtract": "NumpadSubtract",
        "decimal": "NumpadDecimal",
        "divide": "NumpadDivide",
        "f1": "F1",
        "f2": "F2",
        "f3": "F3",
        "f4": "F4",
        "f5": "F5",
        "f6": "F6",
        "f7": "F7",
        "f8": "F8",
        "f9": "F9",
        "f10": "F10",
        "f11": "F11",
        "f12": "F12",
    }

    modifiers = [
        key_mapping.get(part.lower(), part)
        for part in key_parts
        if part.lower() in ["ctrl", "alt", "shift", "super", "command", "meta"]
    ]

    keys = [
        key_mapping.get(part.lower(), part)
        for part in key_parts
        if part.lower() not in ["ctrl", "alt", "shift", "super", "command", "meta"]
    ]

    return KeyMapping(modifiers=modifiers, keys=keys)

async def read_with_retry(page, op, *args, retries=3, backoff=0.12):
    for i in range(retries):
        try:
            await page.wait_for_load_state("domcontentloaded")
            return await op(*args)         
        except PwError as e:
            if "Execution context was destroyed" in str(e) and i < retries-1:
                await asyncio.sleep(backoff * (i + 1))  
                continue
            raise
        
async def screenshot_with_retry(page, *, retries=3, backoff=0.15, **kwargs):
    """
    Standardize screenshots after DOM is ready; on navigation/context-destroyed/slow rendering events, back off briefly and retry.
    Pass kwargs through directly to page.screenshot() (e.g., path=, full_page=, etc.).
    """
    for i in range(retries + 1):
        try:
            await page.wait_for_load_state("domcontentloaded")
            # Disable animations to reduce "unstable frame" timeouts
            return await page.screenshot(animations="disabled", timeout=45000, **kwargs)
        except (PwTimeout, PwError) as e:
            s = str(e)
            transient = (
                "Execution context was destroyed" in s
                or "Target closed" in s
                or "waiting for fonts" in s
                or "taking page screenshot" in s
            )
            if transient and i < retries:
                await page.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(backoff * (i + 1))  # 0.15s, 0.30s …
                # On first retry, try without full_page if specified
                if i == 0 and kwargs.get("full_page", False):
                    kwargs = {**kwargs, "full_page": False}
                continue
            raise
        
async def _safe_eval(page, script: str):
    try:
        return await page.evaluate(script)
    except PwError as e:
        m = str(e).lower()
        if "execution context was destroyed" in m or "because of a navigation" in m:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            return await page.evaluate(script)
        raise
    


# ========== common tools ==========
async def dom_sig(page):
    """Generate a unique signature for the current page state, including URL, title, and body text length."""
    try:
        return await page.evaluate(
            "() => location.href + '|' + (document.title||'') + '|' + (document.body?.innerText?.length||0)"
        )
    except Exception:
        return page.url + "|?"

async def wait_document_ready(page, timeout=8000):
    await page.wait_for_function(
        "() => ['interactive','complete'].includes(document.readyState)", timeout=timeout
    )

async def wait_layout_stable(page, timeout=2000, frames_ok=2, interval_ms=80):
    """Wait for the page layout to stabilize, defined as consecutive frames with body height change less than 1px."""
    js = f"""
    (n, dt) => new Promise(res => {{
      let ok=0, last=document.body?.getBoundingClientRect().height||0;
      const id=setInterval(()=>{{
        const h=document.body?.getBoundingClientRect().height||0;
        ok = Math.abs(h-last) < 1 ? ok+1 : 0;
        last=h;
        if(ok>=n){{clearInterval(id);res(true);}}
      }}, dt);
      setTimeout(()=>{{clearInterval(id);res(false);}}, {timeout});
    }})
    """
    try:
        await page.evaluate(js, [int(frames_ok), int(interval_ms), int(timeout)])
    except Exception:
        pass

async def safe_eval(page, code):
    """Evaluate JavaScript code on the page, handling transient errors like navigation or context destruction."""
    try:
        return await page.evaluate(code)
    except PWError as e:
        m = str(e).lower()
        if "execution context was destroyed" in m or "navigat" in m:
            try: await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception: pass
            return await page.evaluate(code)
        raise
    
async def scroll_metrics(page):
    # Return scroll position, total height, and viewport height to avoid division by zero
    return await _safe_eval(page, """
      () => {
        const de = document.documentElement;
        const root = document.scrollingElement || de;
        const top = root.scrollTop || window.pageYOffset || 0;
        const total = Math.max(1, root.scrollHeight || de.scrollHeight || 1);
        const vh = Math.max(1, de.clientHeight || window.innerHeight || 1);
        return {top, total, vh};
      }
    """)

# ========== scroll  ==========
async def maybe_scroll_into_view(page, x, y):
    """Scroll the page to ensure the point (x, y) is within the viewport."""
    vp = await page.evaluate("() => ({w: innerWidth, h: innerHeight, sx: scrollX, sy: scrollY})")
    if 0 <= x < vp["w"] and 0 <= y < vp["h"]:
        return False
    await page.evaluate(
        "([x,y,sy]) => window.scrollTo({top: Math.max(0, y + sy - innerHeight/2), behavior:'instant'})",
        [x, y, vp["sy"]],
    )
    return True

async def probe_point(page, x, y):
    """
    Probe the element at (x, y) to check visibility, pointer events, and navigation likelihood.
    """
    js = """
    ([x,y]) => {
      const el = document.elementFromPoint(x,y);
      if (!el) return null;
      const cs = getComputedStyle(el);
      const visible = cs && cs.visibility!=='hidden' && cs.display!=='none' && parseFloat(cs.opacity||'1')>0.01;
      const pe = cs && cs.pointerEvents!=='none';
      const link = el.closest('a[href], [role="link"][href]');
      const submit = el.closest('button[type="submit"], input[type="submit"]');
      const newTab = link && (link.target==='_blank' || (link.rel||'').includes('noopener'));
      return { visible, pe, navLikely: !!(link||submit), popupLikely: !!newTab };
    }
    """
    return await page.evaluate(js, [x, y])

# ========== safe operation: Click / Key / Scroll / Tabs / History ==========
async def safe_click_at(page, x: int, y: int, nav_timeout=10000) -> bool:
    """Safely click at (x, y) on the page, handling navigation, context destruction, and layout stability."""
    before = await dom_sig(page)
    await wait_document_ready(page)
    await maybe_scroll_into_view(page, x, y)
    await wait_layout_stable(page)

    info = await probe_point(page, x, y)
    if not info or not (info["visible"] and info["pe"]):
        
        await asyncio.sleep(0.12)
        info = await probe_point(page, x, y)
        if not info or not (info["visible"] and info["pe"]):
            return False  

    try:
        if info.get("popupLikely"):  # 可能 target=_blank
            async with page.expect_popup() as pctx:
                await page.mouse.click(int(x), int(y))
            newp = await pctx.value    # ← 注意 await
            await newp.wait_for_load_state("domcontentloaded")
            
            return True

        if info.get("navLikely"):
            async with page.expect_navigation(wait_until="domcontentloaded", timeout=nav_timeout):
                await page.mouse.click(int(x), int(y))
            return True

        await page.mouse.click(int(x), int(y))     
        await asyncio.sleep(0.05)                  
    except PWError as e:
        msg = str(e).lower()
        if "execution context was destroyed" in msg or "navigat" in msg:
            try: await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception: pass
        else:
            raise

    # SPA 
    after = await dom_sig(page)
    return after != before or True

async def safe_key(page, key: str, timeout_nav=10000) -> bool:
    k = (key or "").strip()
    if k.lower() == "return":
        k = "Enter"

    ## Navigate keys
    nav_keys = {"Enter", "Alt+Left", "Alt+Right"}
    if k in nav_keys:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=timeout_nav):
            await page.keyboard.press(k)
        return True

    ## Non-navigate keys
    try:
        focused = await safe_eval(page, "() => document.activeElement && document.activeElement !== document.body")
        if not focused:
            await page.focus("body")
    except Exception:
        pass
    await page.keyboard.press(k)
    await asyncio.sleep(0.05)
    return True

async def safe_scroll(page, dy: int) -> bool:
    before = await scroll_metrics(page)

    # mouse wheel scroll
    await page.mouse.wheel(delta_x=0,delta_y=int(dy))

    # wait for layout stable
    await wait_layout_stable(page, timeout=1200, frames_ok=2, interval_ms=60)

    # check if scroll happened
    after = await scroll_metrics(page)
    if after["top"] != before["top"]:
        return True

    # fallback: scrollBy
    await _safe_eval(page, f"() => window.scrollBy({{top:{int(dy)}, left:0, behavior:'instant'}})")
    await wait_layout_stable(page, timeout=800, frames_ok=2, interval_ms=60)
    after2 = await scroll_metrics(page)
    return after2["top"] != before["top"]

async def switch_to_page(context, target_index: int = -1):
    pages = context.pages
    if not pages:
        return None
    target = pages[-1] if target_index < 0 else pages[min(target_index, len(pages)-1)]
    await target.bring_to_front()
    await target.wait_for_load_state("domcontentloaded")
    return target

async def safe_go_back(page, timeout_nav=10000):
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=timeout_nav):
        await page.go_back()
    return True

async def safe_go_forward(page, timeout_nav=10000):
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=timeout_nav):
        await page.go_forward()
    return True