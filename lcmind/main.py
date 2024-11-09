import copy
import ctypes
from   ctypes import windll
import ctypes.wintypes
import cv2
from   dataclasses import dataclass, field
import datetime
import glob
import importlib
import inspect
import keyboard
import numpy
import os
import requests
import sys
import threading
import time
import win32api
import win32con
import win32gui

#FUTURE: remove pyautogui (no multi-monitor and bloated), win32gui, win32api, and keyboard

'''Known bugs
mirror_route: fixed with new loc but system is fragile and needs deeper testing. revamped disaser recovery but untested
job_mirror: blindly accepts mirrors in progress and declines existing rewards. need to verify these
job_mirror: new logic for erroring out when too much time is spent in unknown state
mirror_choose_ego_gift: untested new fix for bug with ego+reward card combo
event_resolve: bespoke choices seem fragile. changed logic to reflect event_choice being 0 indexed, choices will be very different now

battle_prepare_team: incorrectly identifies 3/5 team as 5/5, alerts 5/5 as undermanned (maybe fixed?)
job_stamina_buy_with_lunacy: stops at 7 resets when should be 9
claim_battlepass: sometimes click gets missed, so there might be outstanding claims
'''
'''Win-Loss records for various themes, for pseudo Poise team
1-0 Degraded Gloom [34]
1-0 Sinking Pang
0-1 To be Cleaved (fire bird boss)
'''
################################################################################
## Defy organization
################################################################################

@dataclass
class State:
    # Config
        # strategy
    ai_team_mirror_sinner_priority: list[str] = ('Don Quixote', 'Ryoushu', 'Outis', 'Yi Sang', 'Rodion', 'Hong Lu', 'Faust', 'Heathcliff', 'Ishmael', 'Sinclair', 'Meursult', 'Gregor')
    ai_team_lux_sinner_priority: list[str] = ('Don Quixote', 'Ryoushu', 'Outis', 'Yi Sang', 'Rodion', 'Hong Lu', 'Faust', 'Heathcliff', 'Ishmael', 'Sinclair', 'Meursult', 'Gregor')
    stamina_daily_resets: int = 9
    
    mirror_decline_partial_rewards: bool = True # anything less than 100% is considered a failure/partial
    mirror_decline_previous_rewards: bool = True # if there's a previous run to collect (which are always a partial)

        # AI vs manual control settings
    ai_manual_override_routing: bool = False # if true, ignores the normal AI settings below
    ai_themes: bool = True
    ai_routing: bool = True
    ai_reward_cards: bool = True
    ai_reward_egos: bool = True
    ai_events: bool = True
    ai_shop_chair: bool = True
    ai_shop_buy: bool = True
    ai_starting_gifts: bool = True
    ai_team_select: bool = True
    stop_for_inspecting_unknowns: bool = False

        # logging
    log_video: bool = True
    log_directory: str = 'R:/tmp/logs/limbus_company'
    log_levels_disabled: list[str] = ('TRACE',)

        # misc
    disable_dpi_requirements: bool = False # bot doesn't function well, but useful for debugging

    # State
    daily_exp_incomplete: bool | None = None # None means unknown state
    daily_thread_incomplete: bool | None = None
    battle_team_type_mirror: bool = True
    current_floor_theme: str | None = None

    job: str | None = None
    subjob: str | None = None
    log_app_start_time: str = None
    module_mtime: float = 0

    # Control
    paused: bool = False
    halt: bool = False
    
    # Stats
    stats_grind_runs_attempted: int = 0
    stats_grind_runs_completed: int = 0
    stats_mirror_successes: int = 0
    stats_mirror_failures: int = 0
    stats_mirror_started: int = 0
    stats_stamina_resets: int = 0
    stats_battles_num: int = 0
    stats_battle_rounds: int = 0
    stats_battles: dict = field( default_factory=lambda: {} ) # BattleName -> { turns, events, errors, completed }
    stats_events_num: int = 0

    stats_dummy: int = 0

def ai_set_manual_routing():
    st.ai_themes = False
    st.ai_routing = False
    st.ai_reward_cards = False
    st.ai_reward_egos = False
    st.ai_events = False
    st.ai_shop_chair = False
    st.ai_shop_buy = False
    st.ai_starting_gifts = False
    st.ai_team_select = False
    st.stop_for_inspecting_unknowns = True

@dataclass
class Vec2:
    x: int = 0
    y: int = 0

def reload_mod( module=None ):
    global st, win

    mod_mtime = os.path.getmtime( sys.modules[ main.__module__ ].__file__ )
    if mod_mtime > st.module_mtime:
        st.module_mtime = mod_mtime
    
        try:
            bak_win, bak_st = copy.copy( win ), copy.copy( st ) #TODO verify doesn't need deepcopy
            importlib.reload( sys.modules[ main.__module__ ] )
            win, st = bak_win, bak_st
        except SyntaxError as e:
            return loge( f'SyntaxError: {e}' )
        logw( 'Reloaded module' )

################################################################################
## Logging
################################################################################

def discord_test(): sys.modules[ main.__module__ ].__dict__['discord_test2']()
def discord_test2():
    logi( "Discord Test Start" )
    try:
        #log_discord_send( 'CRTICIAL', 'discord_test', 'The quick brown fox jumped over the lazy dog' )
        log_discord_clear()
        #log_discord_send( 'STATS', 'discord_test', 'Run stats', {'Runs':'1','Success':'1','Failures':'0','Avg Time':'1:23'} )
        #log_discord_send( 'STATS', 'discord_test', 'Theme acc', [ ('Theme1',0.951), ('Theme2',0.952), ('Theme3',0.953) ] )
    except Exception as e:
        loge( f"Discord Test Error: {e}" )
    logi( "Discord Test End" )

def log_discord_clear():
    # Load all outstanding messages
    with open( f'{st.log_directory}/discord_messages.txt', 'r' ) as f:
        sent_mids = [ mid for mid in f.read().split('\n') if mid ]
    logi( f'Loaded {len(sent_mids)} messages for deletion' )
    
    # Attempt to delete each one
    failed_to_delete_mids = []
    for mid in sent_mids:
        webhook_url = f"https://discord.com/api/webhooks/1185293371338661929/DEkEdArK862lbrOZwdH-RAP-9n9tbxdg6GiXRgNsM1sS_0Ych1O8_YLni-fJSvIX1aMj/messages/{mid}"
        r = requests.delete( webhook_url, json={} )
        if r.status_code != 204:
            failed_to_delete_mids.append( mid )
    
    # Save the ones that failed
    with open( f'{st.log_directory}/discord_messages.txt', 'w' ) as f:
        for mid in failed_to_delete_mids:
            f.write( f'{mid}\n' )
    loge( f'Saved {len(failed_to_delete_mids)} messages for future deletion' )

def log_discord_send( level, tag, msg, fields=None ):
    # Reforge fields into list of tuples, with max 10 supported by Discord
    fields = fields.items() if isinstance( fields, dict ) else fields or []
    if len(fields) > 10:
        fields = fields[:10]
        logt( 'Discord message has too many fields ({len(fields)}). Truncating to 10' )

    # Generate message with embed
    darktide_colors = {
        "gray": 0x979797,
        "green": 0x5AAC65,
        "blue": 0x4C82C2,
        "purple": 0x8E5DC2,
        "orange": 0xCE8632,
        "red": 0xC4230E
    }
    level2color = {
        "TRACE": 0xD3D3D3,      # Light Gray
        "DEBUG": 0x808080,      # Gray
        "INFO": 0x0000FF,       # Blue
        "WARNING": 0xFFFF00,    # Yellow
        "ERROR": 0xFF0000,      # Red
        "CRITICAL": 0x8B0000,   # Dark Red
        "STATS": 0x5AAC65,      # Green
    }
    emb = {
        'title': f"{tag}",
        'color': level2color[ level ],
        'description': f"{msg}",
        'footer': { 'text': f"Footer" },
        'fields': [],
    }
    for k,v in fields:
        if isinstance(v,float): v = f'{v:.4f}'
        emb['fields'].append( {'name':str(k), 'value':str(v), 'inline':True} )

    # Send message
    webhook_url = f"https://discord.com/api/webhooks/1185293371338661929/DEkEdArK862lbrOZwdH-RAP-9n9tbxdg6GiXRgNsM1sS_0Ych1O8_YLni-fJSvIX1aMj?wait=true"
    r = requests.post( webhook_url, json={'embeds': [emb]} )
    if r.status_code != 200:
        loge( f'Discord Request Error {r.status_code}: {r.text}' )
        return

    # Save message id for later deletion
    msg_id = r.json()['id']
    with open( f'{st.log_directory}/discord_messages.txt', 'a' ) as f:
        f.write( f'{msg_id}\n' )

def logc( msg ): log( level='CRITICAL', msg=msg )
def loge( msg ): log( level='ERROR', msg=msg )
def logw( msg ): log( level='WARNING', msg=msg )
def logi( msg ): log( level='INFO', msg=msg )
def logd( msg ): log( level='DEBUG', msg=msg )
def logt( msg ): log( level='TRACE', msg=msg )
def log_stats( msg, kvs=None ): log( level='STATS', msg=msg, kvs=kvs )

def log_time(): return time.strftime("%Y-%m-%d_%H-%M-%S", time.gmtime()) # not quite iso 8601
def log_colorize_text( text:str, fg:str|None=None, bg:str|None=None, mode:str|None=None ) -> str:
    '''Colorize text for terminal printing. Bright not supported since compatibility is low'''
    # https://gist.github.com/fnky/458719343aabd01cfb17a3a4f7296797
    # 30 for color, +10 background +60 bright
    ansii_graphics_mode = { 'Reset':0, 'Bold':1, 'Dim':2, 'Italic':3, 'Underline':4, 'Blink':5, 'Reverse':7, 'Hidden':8, 'Strikethrough':9 }
    ansii_color = { 'Black':0, 'Red':1, 'Green':2, 'Yellow':3, 'Blue':4, 'Magenta':5, 'Cyan':6, 'White':7, 'Default':9, 'Reset':0 }
    
    ESC = '\033'
    CSI = '['
    sequence = ';'.join( str( part ) for part in [
        ansii_graphics_mode[ mode ] if mode else None,
        ( ansii_color[ fg ] + 30 ) if fg else None,
        ( ansii_color[ bg ] + 30+10 ) if bg else None,
        ] if part )

    code_begin = ESC+CSI+ sequence +'m'
    code_end = ESC+CSI+'m'
    return code_begin + text + code_end

def log( msg='', level=None, kvs=None ):
    # Derive meta information by crawling the stack
    thread, job, subjob, caller = None, None, None, None
    for frame in inspect.stack():
        if caller is None and not frame.function.startswith( 'log' ): caller = frame.function
        if thread is None and frame.function.startswith( 'thread_' ): thread = frame.function[7:]
        if job is None and frame.function.startswith( 'job_' ): job = frame.function[4:]
        if subjob is None and frame.function.startswith( 'subjob_' ): subjob = frame.function[7:]
    
    mini_time = datetime.datetime.now( datetime.timezone.utc ).strftime( "%H-%M-%S-%f" )
    if job and caller.startswith('job_'): caller = None # simplify tag for job base function
    
    # Generate tag from meta info, then final text
    tag = '.'.join( x for x in [mini_time,level,job,caller] if x )
    tag = f'[{tag}]'
    text = f'{tag} {msg} {kvs}' if kvs is not None else f'{tag} {msg}'

    tag_discord = '.'.join( x for x in [job,caller] if x )
    text_discord = f'{msg}'

    # Colorized version for terminal output, based on log level
    text_colored = text
    if   level == 'CRITICAL': text_colored = log_colorize_text( text, 'Red' )
    elif level == 'ERROR':    text_colored = log_colorize_text( text, 'Red' )
    elif level == 'WARNING':  text_colored = log_colorize_text( text, 'Magenta' )
    elif level == 'INFO':     text_colored = log_colorize_text( text, 'Yellow' )
    elif level == 'DEBUG':    text_colored = log_colorize_text( text, 'Cyan' ) # Blue
    elif level == 'TRACE':    text_colored = log_colorize_text( text, 'White', mode='Dim' )
    elif level == 'STATS':     text_colored = log_colorize_text( text, 'Green' )

    # Print to terminal and write to log file
    if level not in st.log_levels_disabled: print( text_colored )

    with open( f'{st.log_directory}/console_{st.log_app_start_time}.txt', 'a' ) as f:
        f.write( text_colored +'\n' )
    
    if level in ['CRITICAL', 'STATS']:
        log_discord_send( level, tag_discord, text_discord, kvs )

################################################################################
## Platform specific functionality for constructing basic image bot verbs
################################################################################

@dataclass
class Window:
    pos: Vec2 = field( default_factory=lambda: Vec2(0,0) )
    size: Vec2 = field( default_factory=lambda: Vec2(1280,720) )
    dpi: Vec2 = field( default_factory=lambda: Vec2(144,144) )

    hwnd: int = 0
    dc: int = 0
    screen_size: Vec2 = field( default_factory=lambda: Vec2(0,0) )

def win_init():
    '''Find window and normalize it'''
    win.hwnd = win32gui.FindWindow( "UnityWndClass", "LimbusCompany" )
    assert win.hwnd, 'Failed to find window handle'
    win.dc = windll.user32.GetDC( win.hwnd )
    assert win.dc, 'Failed to get window device context'
    win_fix()
    err = win_verify()
    if err:
        logc( err )
        raise Exception( err )

def win_cleanup():
    if win.hwnd and win.dc:
        windll.user32.ReleaseDC( win.hwnd, win.dc )

def win_fix():
    '''Normalize window position and size and foreground it'''
    windll.user32.SetProcessDPIAware()
    if windll.user32.IsIconic( win.hwnd ):
        windll.user32.ShowWindow( win.hwnd, win32con.SW_RESTORE )
    windll.user32.SetForegroundWindow( win.hwnd )
    windll.user32.SetWindowPos( win.hwnd, 0, win.pos.x, win.pos.y, win.size.x, win.size.y, win32con.SWP_NOZORDER )
    # update screen size
    win.screen_size.x = windll.gdi32.GetDeviceCaps( win.dc, win32con.DESKTOPHORZRES )
    win.screen_size.y = windll.gdi32.GetDeviceCaps( win.dc, win32con.DESKTOPVERTRES )
    
def win_verify() -> str | None:
    '''Verify window DPI scaling'''
    logd( 'Verifying window DPI scaling' )
    dpi_x = windll.gdi32.GetDeviceCaps( win.dc, win32con.LOGPIXELSX ) # enums HORZRES DESKTOPHORZRES LOGPIXELSX
    dpi_y = windll.gdi32.GetDeviceCaps( win.dc, win32con.LOGPIXELSY )
    if not st.disable_dpi_requirements:
        if win.dpi != Vec2(dpi_x,dpi_y): return f"Window DPI is {dpi_x},{dpi_y} instead of {win.dpi}"

    logd( 'Verifying window position and size' )
    x,y, width,height = win32gui.GetWindowRect( win.hwnd )
    if win.pos != Vec2(x,y): return f"Window position is {x},{y} instead of {win.pos}"
    if win.size != Vec2(width,height): return f"Window size is {width},{height} instead of {win.size}"

def win_screenshot():
    '''Take screenshot of window'''
    import pyautogui
    return pyautogui.screenshot( region=(win.pos.x,win.pos.y,win.size.x,win.size.y) )

def input_mouse_get_pos() -> Vec2:
    class CPoint( ctypes.Structure ):
        _fields_ = [ ('x', ctypes.c_long), ('y', ctypes.c_long) ]
    point = CPoint()
    windll.user32.GetCursorPos( ctypes.byref( point ) )
    return Vec2( point.x, point.y )

def input_mouse_move( pos: Vec2, wait=0.3 ):
    pos = Vec2( pos.x+win.pos.x, pos.y+win.pos.y )
    windll.user32.SetCursorPos( pos.x, pos.y )
    sleep( wait )
    
def input_mouse_click( pos: Vec2, wait=0.3, move_mouse_away=True ):
    '''Click mouse button at position'''
    pos = Vec2( pos.x+win.pos.x, pos.y+win.pos.y )
    windll.user32.SetCursorPos( pos.x, pos.y )
    windll.user32.mouse_event( win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0 )
    windll.user32.mouse_event( win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0 )
    sleep( wait )
    if move_mouse_away:
        windll.user32.SetCursorPos( win.screen_size.x-1, 1 )
        sleep( 0.1 )

def input_mouse_drag( from_pos: Vec2, to_pos: Vec2, wait=0.3, move_mouse_away=True, steps=10 ):
    from_pos = Vec2( from_pos.x+win.pos.x, from_pos.y+win.pos.y )
    to_pos = Vec2( to_pos.x+win.pos.x, to_pos.y+win.pos.y )
    windll.user32.SetCursorPos( from_pos.x, from_pos.y )
    sleep(0.1)
    windll.user32.mouse_event(  win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0 )
    sleep(0.1)
    pos = Vec2( from_pos.x, from_pos.y )
    for i in range(steps):
        # lerp
        pos.x = int( from_pos.x + (to_pos.x-from_pos.x) *i/steps )
        pos.y = int( from_pos.y + (to_pos.y-from_pos.y) *i/steps )
        # normalize for mouse_event
        pos.x = int( pos.x * 65535/win.screen_size.x )
        pos.y = int( pos.y * 65535/win.screen_size.y )
        logt( f'mouse dragging {pos}' )
        windll.user32.mouse_event( win32con.MOUSEEVENTF_ABSOLUTE | win32con.MOUSEEVENTF_MOVE, pos.x, pos.y, 0, 0 )
        sleep( 1 / steps )
    windll.user32.mouse_event( win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0 )
    sleep( wait )
    if move_mouse_away:
        windll.user32.SetCursorPos( win.screen_size.x-1, 1 )
        sleep( 0.1 )

def input_mouse_scroll( pos, scroll_times=5, scroll_up=True ):
    scroll_delta = -120 if scroll_up else 120
    for i in range(scroll_times):
        #print( f'Scrolling by {scroll_delta} for the {i} time' )
        windll.user32.SetCursorPos( pos.x, pos.y )
        sleep( 0.1 )
        windll.user32.mouse_event( win32con.MOUSEEVENTF_WHEEL, 0, 0, ctypes.wintypes.DWORD(scroll_delta), 0 )
    windll.user32.SetCursorPos( win.screen_size.x-1, 1 )
    sleep( 0.1 )

def input_keyboard_press( key, wait_up=0.01, wait=0.3 ):
    def _key2vk( k ):
        if k.startswith('VK'):  return getattr( win32con, k )
        elif k == 'ENTER':      return win32con.VK_RETURN
        elif k == 'BACKSPACE':  return win32con.VK_BACK
        elif k == 'ESCAPE':     return win32con.VK_ESCAPE
        else:                   return win32api.VkKeyScan( k )
    k = _key2vk( key )
    win32api.keybd_event( k, 0, 0, 0 )
    sleep( wait_up )
    win32api.keybd_event( k, 0, win32con.KEYEVENTF_KEYUP, 0 )
    sleep( 0.3 )

def sleep( seconds ):
    time.sleep( seconds )

################################################################################
## General image bot verbs for constructing jobs
################################################################################

def img_find( template_name: str, threshold=0.8, use_best=True, use_grey_normalization=False, color_space=cv2.COLOR_RGB2GRAY ) -> tuple[Vec2 | None, float]:
    # Load template image
    template_path = f'res/{template_name}.png'
    if not os.path.exists( template_path ): raise FileNotFoundError( f'File DNE for template image {template_path}' )
    template_img = cv2.imread( template_path, cv2.IMREAD_GRAYSCALE )
    if template_img is None: raise FileNotFoundError( f'Failed to load template image {template_path}' )

    # Load screenshot image
    screen_img = cv2.cvtColor( numpy.array(win_screenshot()), color_space )

    if use_grey_normalization:
        clahe = cv2.createCLAHE( clipLimit=2.0, tileGridSize=(8,8) )
        template_img = clahe.apply( template_img )
        screen_img = clahe.apply( screen_img )
        

    # Find template in screenshot
    res = cv2.matchTemplate( screen_img, template_img, cv2.TM_CCOEFF_NORMED )

    loc = None
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc( res )
    if use_best:
        #print( f"img_find max_val={max_val} max_loc={max_loc}" )
        if max_val > threshold: loc = max_loc
        else: return (None, max_val)
    else:
        locs = numpy.where( res >= threshold )
        if locs: loc = list(zip(*locs[::-1]))[0] # reverse x,y to y,x
        else: return (None, max_val)
    
    # Find center of template at best match location
    h,w = template_img.shape
    center = Vec2( loc[0]+w//2, loc[1]+h//2 )
    logt( f"found {template_name} at {center} acc {max_val}" )
    return (center, max_val)

def find( template_name: str, threshold=0.8, use_best=True, timeout=1.0, can_fail=True ):
    t0 = time.time()
    acc = -1
    while time.time()-t0 < timeout:
        pos, acc = img_find( template_name, threshold, use_best )
        if pos: return pos
        sleep(0.1)
    if not can_fail: raise TimeoutError( f"Failed to find {template_name} in {timeout} sec. Max acc {acc}" )
    return None

def has( template_name: str, threshold=0.8, use_best=True ):
    pos, _acc = img_find( template_name, threshold, use_best )
    return pos

def has_acc( template_name: str ):
    _pos, acc = img_find( template_name, use_best=True )
    logt( f"ACC {acc:.6f} for IMG {template_name}" )
    return acc

def click( template_name: str, wait=0.6, can_fail=False, threshold=0.75, use_best=True, timeout=1.0 ):
    pos = find( template_name, threshold, use_best, timeout, can_fail )
    if pos: input_mouse_click( pos, wait )
    return pos

def nclick( template_name: str, wait=0.6, can_fail=False, threshold=0.75, use_best=True, timeout=1.0 ):
    '''Dry run version of click'''
    pos = find( template_name, threshold, use_best, timeout, can_fail )
    if pos: logc( f"would click {template_name} at {pos}" )
    return pos

def click_drag( template_name: str, dest_offset: Vec2, wait=0.9, can_fail=False, threshold=0.75, use_best=True, timeout=1.0 ):
    pos = find( template_name, threshold, use_best, timeout, can_fail )
    if pos: input_mouse_drag( pos, Vec2(pos.x+dest_offset.x, pos.y+dest_offset.y), wait )
    return pos

def press( key, wait=0.5 ):
    input_keyboard_press( key, wait )

################################################################################
## Limbus Specific - Bot Jobs
################################################################################

def detect_battle_prepare() -> bool:
    return has( 'team/Announcer', threshold=0.7 )
def detect_loading() -> bool:
    return has( 'CombatTips' ) or has( 'Wait' )
def detect_battle_combat() -> bool:
    return has( 'battle/WinRate' ) or has( 'battle/Start' )

def job_stamina_convert_to_modules():
    logi( 'start' )
    click( 'initMenu/greenPai' )
    click( 'initMenu/maxModule' )
    click( 'initMenu/confirm' )
    click( 'initMenu/cancel', can_fail=True )

def job_stamina_buy_with_lunacy():
    logi( 'start' )
    click( 'initMenu/greenPai' )
    click( 'initMenu/UseLunary' )
    # old safe strat was just 1/d by looking for first buy image
    # now we do less safe N/day strat by looking for N+1 reset imagery
    #if find( 'initMenu/FirstBuy', threshold=0.9 ):
    if not find( f'initMenu/StaminaReset{st.stamina_daily_resets}', threshold=0.9 ): # slightly inaccurate. 7 seen as 9 but close enough for now
        click( 'initMenu/confirm' )
        st.stats_stamina_resets += 1
        logd( f'bought {st.stats_stamina_resets} resets since startup' )
    else:
        logd( f'already bought {st.stamina_daily_resets} resets today' )
    click( 'initMenu/cancel', can_fail=True )

def job_claim_mail():
    logi( 'start' )
    click( 'initMenu/window' )
    click( 'initMenu/Mail' )
    click( 'initMenu/ClaimAll' )
    click( 'initMenu/MailConfirm', can_fail=True )
    click( 'initMenu/CloseMail' )

def job_claim_battlepass():
    logi( 'start' )
    click( 'initMenu/window' )
    click( 'prize/Season5BattlePass', wait=0.5 ) # revisit now that wait is fixed
    for _ in range(5):
        click( 'prize/PassMissions' )
        if find( 'prize/Weekly' ): break
    else: raise TimeoutError( 'Failed to find weekly missions' )
    pos = Vec2(520,240)
    for i in range(5):
        input_mouse_click( pos )
        pos.y += 90
    
    st.daily_exp_incomplete = find( 'prize/IncompleteDailyExp' ) is not None
    st.daily_thread_incomplete = find( 'prize/IncompleteDailyThread' ) is not None
    logd( f'Daily incompletion status: exp={st.daily_exp_incomplete} thread={st.daily_thread_incomplete}' )
    click( 'prize/Weekly' )
    pos = Vec2(520,240)
    for i in range(5):
        input_mouse_click( pos )
        pos.y += 90
    click( 'goBack/leftarrow' )

def job_daily_exp():
    logi( 'start' )
    logd( 'navigating ui' )
    click( 'initMenu/drive' )
    for _ in range(5):
        click( 'luxcavation/luxcavationEntrance' )
        if find( 'luxcavation/ExpEntrance' ): break
    else: raise TimeoutError( 'Failed to find luxcavation entrance' )
    click( 'luxcavation/ExpEntrance' )
    click( 'luxcavation/EXPDifficultyLv18' )
    logd( 'waiting for team select' )
    find( 'team/Announcer', threshold=0.7, timeout=3.0, can_fail=False )
    battle_prepare_team( False )
    battle_combat()
    if not st.paused:
        click( 'goBack/leftarrow' ) # reset to home but also verify completion

def job_daily_thread():
    logi( 'start' )
    logd( 'navigating ui' )
    click( 'initMenu/drive' )
    for _ in range(5):
        click( 'luxcavation/luxcavationEntrance' )
        if find( 'luxcavation/ThreadEntrance' ): break
    else: raise TimeoutError( 'Failed to find luxcavation entrance' )
    click( 'luxcavation/ThreadEntrance' )
    click( 'luxcavation/Enter' )
    click( 'luxcavation/ThreadDifficultyLv20' )
    logd( 'waiting for team select' )
    find( 'team/Announcer', threshold=0.7, timeout=3.0, can_fail=False )
    battle_prepare_team( False )
    battle_combat()
    if not st.paused:
        click( 'goBack/leftarrow' ) # reset to home but also verify completion

def battle_prepare_team( battle_team_type_mirror:bool|None = None ):
    battle_team_type_mirror = battle_team_type_mirror if battle_team_type_mirror is not None else st.battle_team_type_mirror

    logi( 'start' )
    # Choose team order
    sinners_in_order = ['Yi Sang', 'Faust', 'Don Quixote', 'Ryoushu', 'Meursult', 'Hong Lu', 'Heathcliff', 'Ishmael', 'Rodion', 'Sinclair', 'Outis', 'Gregor']
    sinner_priority_list = st.ai_team_mirror_sinner_priority if battle_team_type_mirror else st.ai_team_lux_sinner_priority
    if len(set( sinner_priority_list )) != 12:
        raise ValueError( 'Sinner priority list must contain all 12 sinners exactly once' )
    
    full_template = 'team/FullTeam66' if battle_team_type_mirror else 'team/FullTeam55'
    if not find( full_template, threshold=0.96 ):
        logd( 'Team not prepared, redoing selection' )
        click( 'team/ClearSelection', wait=0.8 )
        press( 'ENTER' )
        pos = find( 'team/Announcer', threshold=0.7, can_fail=False )
        for sinner_name in sinner_priority_list:
            idx = sinners_in_order.index( sinner_name )
            rel_pos = Vec2( (idx % 6 +1)* 140, (idx//6)*200 + 100 )
            input_mouse_click( Vec2(pos.x+rel_pos.x, pos.y+rel_pos.y) )
        if not find( full_template, threshold=0.96 ):
            loge( "Team seems to be undermanned. Either we're losing or detection is flawed" )
    else:
        logd( 'Team is already prepared' )

    # Now start battle
    press( 'ENTER' )

    # Wait for battle to load
    logd( 'waiting for battle to load' )
    while not detect_battle_combat() and not st.paused:
        if detect_loading(): logd( 'loading...' )
        else: logw( 'unknown state' ) #TODO consider pressing ENTER if stuck
        sleep(1.0)
    
    logi( 'Battle is loaded' )

def battle_combat( battle_state_unknown_timeout=5 ):
    logi( 'start' )
    error_count = 0
    stats = { 'turns':0, 'events':0, 'completed':False, 'errors':0 }
    st.stats_battles[ st.stats_battles_num ] = stats
    st.stats_battles_num += 1
    while not st.paused: # yields for pause, so don't assume function return means battle is over
        reload_mod()
        logt( f'stats {stats}' )
        # Regular combat
        if detect_battle_combat():
            stats[ 'turns' ] += 1
            st.stats_battle_rounds += 1
            logd( f"Turn {stats[ 'turns' ]} -> WinRate" )
            press( 'p' )
            press( 'ENTER' )
            if click( 'battle/WinRate', can_fail=True ):
                press( 'ENTER' )
            error_count = 0
        elif has( 'battle/battlePause' ):
            logt( 'animating turn...' )
            error_count = 0
        elif detect_loading():
            logt( 'loading...' )
            error_count = 0
        # Battle interuptions (like events)
        elif has( 'event/Skip' ):
            stats[ 'events' ] += 1
            event_resolve()
            error_count = 0
        # Unclear
        elif not has( 'mirror/mirror4/way/mirror4MapSign' ) and has( 'battle/trianglePause' ):
            logd( 'Manager level up' )
            click( 'battle/trianglePause' )
            press( 'ENTER' )
            error_count = 0
        # End of battle
        elif has( 'battle/levelUpConfirm' ):
            logt( 'End level up' )
            click( 'battle/levelUpConfirm' )
        elif has( 'battle/blackWordConfirm' ) or has( 'battle/confirm' ):
            logt( 'End confirm' )
            click( 'battle/blackWordConfirm', can_fail=True ) or click( 'battle/confirm' )
            break
        elif has( 'mirror/mirror4/way/RewardCard/RewardCardSign' ):
            logt( 'End with reward card' )
            break
        elif has( 'mirror/mirror4/ego/egoGift' ):
            logt( 'End with ego gift' )
            break
        elif has( 'mirror/mirror4/way/mirror4MapSign' ):
            logt( 'End without fanfare' )
            break
        # Unknown state / error handling
        else:
            stats[ 'errors' ] += 1
            logt( f"Battle state unknown #{stats[ 'errors' ]}" ) # usualy minor animation for new wave or animating reward screen
            if error_count > battle_state_unknown_timeout:
                raise TimeoutError( 'Battle state unknown for too long' )
            error_count += 1
        sleep(1.0)
    stats[ 'completed' ] = True
    logi( f'end - stats{stats}' )

def event_choice( choice: int ): # choice slot 0..2
    pos = has( 'event/Skip' )
    if pos:
        input_mouse_click( Vec2(pos.x+150, pos.y -100 +choice*100), wait=1.5 )

def event_resolve( max_skip_attempts=10 ):
    logi( 'start' )
    st.stats_events_num += 1
    if not st.ai_events:
        logc( 'HUMAN Handle event' )
        return control_wait_for_human()
    skip_attempts = 0
    while not st.paused:
        if has( 'mirror/mirror4/ProductCatalogue/ProductCatalogue' ):
            if has( 'mirror/mirror4/ProductCatalogue/FuseGifts' ):
                logd( 'Event is a shop (chair)' )
                mirror_shop_chair() if st.ai_shop_chair else control_wait_for_human()
            elif has( 'mirror/mirror4/ProductCatalogue/PurchaseEGO' ):
                logd( 'Event is a shop (buy)' )
                mirror_shop_buy() if st.ai_shop_buy else control_wait_for_human()
            break
        elif has( 'event/ChooseCheck' ):
            logd( 'Event choose sinner to perform check' )
            prio = 'veryhigh high Normal Low VeryLow'.split()
            for p in prio:
                if has( f'event/{p}' ):
                    click( f'event/{p}' )
                    break
            else:
                raise TimeoutError( 'Failed to find valid check difficulty' )
            click( 'event/Commence' )
            skip_attempts = 0
        elif has( 'event/Continue' ) or has( 'event/Proceed' ) or has( 'event/ToBattle' ) or has( 'event/CommenceBattle' ):
            logd( 'Event over' )
            has( 'event/Continue' ) and click( 'event/Continue' )
            has( 'event/Proceed' ) and click( 'event/Proceed' )
            has( 'event/ToBattle' ) and click( 'event/ToBattle' )
            has( 'event/CommenceBattle' ) and click( 'event/CommenceBattle' )
            break
        elif has( 'event/Leave' ):
            logd( 'Event leave' )
            click( 'event/Leave' )
            click( 'mirror/mirror4/whiteConfirm' )
            break
        elif has( 'event/Choices' ):
            logd( 'Event bespoke choices' )
            # "Result" from Continue/Proceed and even some Skips gets interpretted as "Choices" banner
            if has( 'encounter/UnDeadMechine1', threshold=0.9 ):
                event_choice(0)
            elif has( 'encounter/UnDeadMechine2', threshold=0.9 ):
                event_choice(1)
            elif has( 'encounter/PinkShoes', threshold=0.9 ):
                event_choice(1)
            elif has( 'encounter/RedKillClock', threshold=0.9 ):
                event_choice(0)
                event_choice(1)
            else:
                event_choice(1)
                event_choice(0)
            #skip_attempts = 0
        elif has( 'event/Skip' ):
            logd( f'Event attempting skip. Try {skip_attempts}' )
            click( 'event/Skip' )
            click( 'event/PassToGainEGO', can_fail=True )
            click( 'event/EGOGiftChoice', can_fail=True )
            skip_attempts += 1
        else:
            logw( 'Unknown event state' )
            skip_attempts += 1
        if skip_attempts > max_skip_attempts:
                raise TimeoutError( 'Event exceeded max skip attempts. Must be stuck' )
        sleep(1.0)

def mirror_shop_chair():
    logd( 'Attempt to aoe heal' )
    if find( 'mirror/mirror4/ProductCatalogue/ChairHealSinner' ):
        click( 'mirror/mirror4/ProductCatalogue/ChairHealSinner' )
        click( 'mirror/mirror4/ProductCatalogue/AllSinnerRest' )
        click( 'event/Skip' )
        click( 'event/Skip' )
        if not click( 'event/Continue', can_fail=True ):
            logd( 'Failed to heal' )
            click( 'mirror/mirror4/ProductCatalogue/DontPurchase' )
    
    #FUTURE: fuse certain combos
    
    # Leave so event handler doesn't get stuck in loop
    click( 'event/Leave' )
    click( 'mirror/mirror4/whiteConfirm' )

def mirror_shop_buy():
    logd( 'Attempt to aoe heal' )
    if find( 'mirror/mirror4/ProductCatalogue/ChairHealSinner' ):
        click( 'mirror/mirror4/ProductCatalogue/ChairHealSinner' )
        click( 'mirror/mirror4/ProductCatalogue/AllSinnerRest' )
        click( 'event/Skip' )
        if not click( 'event/Continue', can_fail=True ):
            logd( 'Failed to heal' )
            click( 'mirror/mirror4/ProductCatalogue/DontPurchase' )
    
    logd( 'Attempt blindly buying egos with remaining cash' )
    ego_locs = [ Vec2(930,350), Vec2(1130,350), Vec2(780,450), Vec2(930,450), Vec2(1130,450) ]
    for ego_loc in ego_locs:
        input_mouse_click( ego_loc )
        if click( 'mirror/mirror4/ProductCatalogue/ConfirmPurchase', can_fail=True ):
            click( 'mirror/mirror4/way/Confirm' )
    
    # Leave so event handler doesn't get stuck in loop
    click( 'event/Leave' )
    click( 'mirror/mirror4/whiteConfirm' )

def mirror_theme( floor, refresh_available=True ):
    st.current_floor_theme = None
    logd( f'Identifying theme packs for floor {floor}' )
    logt( 'waiting for very slow animations to avoid incorrect image detection...' )
    sleep(3)
    themes = {}
    for path in glob.glob('res/mirror/mirror4/jmr_theme/*.png'):
        name = os.path.basename( path )[:-4]
        if name == 'Thumbs': continue # windows thumbs.db junk
        template = f'mirror/mirror4/jmr_theme/{name}'
        themes[ name ] = has_acc( template )
    sorted_by_acc = sorted( themes.items(), key=lambda x:x[1], reverse=True )
    #log_stats( 'Theme accuracies (new ver)', sorted_by_acc[:6] )
    # lowest correct 98.5%, highest incorrect 50.7% run 1 floor 1
    # lowest correct 91.3%, highest incorrect 68.9% run 1 floor 2
    # lowest correct 92.7%, highest incorrect 51.5% run 1 floor 3. P&Pv1 92.7, P&Pv2 99.4
    # lowest correct 99.4%, highest incorrect 58.9% run 1 floor 4
    # lowest correct 85.3%/96.3%, highest incorrect 73.5% run 2 floor 1, 85->98% on 2nd check
    # lowest correct 91.3%, highest incorrect 72.4% run 2 floor 2. first run was awful (63-88%). added delay to fix
    # lowest correct 98.4%, highest incorrect 65.3% run 2 floor 3
    # lowest correct 98.1%, highest incorrect 65.2% run 2 floor 4
    # lowest correct 96.1%, highest incorrect 74.2% run 3 floor 1
    # lowest correct 91.3%, highest incorrect 70.8% run 3 floor 2
    # lowest correct 98.2%, highest incorrect 51.4% run 3 floor 3
    
    if 0:
        logd( 'Info about old theme logic' )
        themes = {}
        for i in range(1,41+1):
            template= f'mirror/mirror4/theme/{i}'
            try:
                themes[ i ] = has_acc( template )
            except FileNotFoundError:
                themes[ i ] = -1 # disabled or no file
        sorted_by_acc_old = sorted( themes.items(), key=lambda x:x[1], reverse=True )
        #log_stats( 'Theme accuracies (old ver)', sorted_by_acc_old[:6] )
    # lowest correct 86.7%, highest incorrect 76.2% run 1 floor 1
    # lowest correct 94.2%, highest incorrect 74.9% run 1 floor 2
    # lowest correct ----%, highest incorrect 68.2% run 1 floor 3
    # lowest correct 88.6%, highest incorrect 70.5% run 1 floor 4
    # lowest correct 93.7%, highest incorrect 76.3% run 2 floor 1
    # lowest correct 94.2%, highest incorrect 74.9% run 2 floor 2
    # lowest correct 85.9%, highest incorrect 70.5% run 2 floor 4
    # lowest correct 86.7%, highest incorrect 76.2% run 3 floor 1
    # lowest correct 76.8%, highest incorrect 68.3% run 3 floor 3 # 76.8 for correct but shadowed
    
    logd( 'Priority based selection method' )
    theme_priorities = {
        'The Forgotten':100,
        'The Outcast':80,
        'The Unloving':70,
        'Emotional Repression':100,
        'Flat-broke Gamblers': 60,

        'Degraded Gloom':100, # Blubbering Toad
        'Sunk Gloom':99,
        'Emotional Judgement':98,
        'Sinking Pang':97,
        'Crushers & Breakers':96, # Blubbering Toad + Papa Bongy + Brazen Bull - Tearful

        "Emotional Seduction":70, # Papa Bongy
        "Hell's Chicken":69, # Papa Bongy
        'Dizzying Waves':68, # Papa Bongy + Fairy Gentleman
        'Repressed Wrath':67, # Papa Bongy + Skin Prophet + Brazier Bull - Tearful
        

        'Slicers & Dicers': 65, # Wayward Passenger + Distorted Bamboo-hatted Kim |6|
        'Emotional Craving':63, # Wayward Passenger + Fairy-Long-Legs |5|
        'Insignificant Envy':40, # Wayward Passenger + kqe-1j-23 + Shock Centipede |6|
        'Pitiful Envy':39, # Wayward Passenger + kqe-1j-23 + Shock Centipede |7|

        'Emotional Indolence':49, # Golden Apple

        'Automated Factory':-28, # Hurtily
        'Vain Pride':-29,
        'Tyrannical Pride':-30,
        
        'To Be Cleaved':-45, # Ardor Blossom Moth
        'Emotional Flood':-47,
        'Burning Haze':-50,
        'Season of the Flame':-51,
        
        } # 0 is the default for themes not given a priority
    
    # Determine best theme based on accuracy of identification, theme priority, and shadow status
    options = {} # Name -> { acc, prio, is_shadow }
    for name, acc in sorted_by_acc[:4]:
        if name.endswith( '.Shadow' ):
            base_name = name[:-7]
            is_shadow = True
        else:
            base_name = name
            is_shadow = False
        prio = theme_priorities.get( base_name, 0 )
        if acc < 0.85: continue
        if is_shadow: prio += 1000 # always take a Shadow so we can unlock it
        options[ name ] = { 'acc':acc, 'prio':prio, 'is_shadow':is_shadow }
    best = sorted( options.items(), key=lambda x: x[1]['prio'], reverse=True )

    # Log selection stats
    #NOTE sometimes we're only offered 3 packs, so imperfect_data can false positive
    imperfect_data = len( [ 1 for _name,data in best if data['prio'] != 0 and not data['is_shadow'] ] ) < 4
    log_stats( f"Theme for floor {floor}{' [imperfect]' if imperfect_data else ''}", {k:f"{'S ' if v['is_shadow'] else ''}{v['prio']} {(v['acc']*100):.3f}%" for k,v in best} )

    if imperfect_data: return control_wait_for_human() #FIXME remove for debug

    # Some potential workarounds in case there's no good options available
    num_acceptable = len( [ 1 for _name,data in best if data['prio'] > 0 ] )
    num_unknowns = 3 - len( best ) # there's always 3-4 packs available, but must assume only 3
    if num_acceptable == 0:
        if refresh_available:
            logd( 'No acceptable themes. Attempting refresh' )
            click( 'mirror/mirror4/theme/refresh', wait=3.0 )
            return mirror_theme( floor, refresh_available=False )
        elif num_unknowns > 0:
            logd( 'No acceptable themes or refresh. Attempting random selection' )
            best = [] # clearing effectively forces random
        else:
            logd( 'No acceptable themes or refresh or unknowns. Choosing least bad' )

    # Try perform drag on best options in order, try refresh, try blind drag
    logd( 'Now actually performing drag on best options in order' )
    
    for name, _data in best:
        template = f'mirror/mirror4/jmr_theme/{name}'
        logd( f'Trying theme {name}' )
        click_drag( template, Vec2(0,300) )
        if not has( 'mirror/mirror4/way/ThemePack/SelectFloor' ) or not has( 'mirror/mirror4/way/ThemePack/ThemePack' ):
            st.current_floor_theme = name
            return
    else: # no drags worked or there weren't an valid options in the first place
        if refresh_available:
            loge( f'Failed to drag any of {len(best)} options. Trying refresh' )
            click( 'mirror/mirror4/theme/refresh', wait=3.0 )
            return mirror_theme( floor, refresh_available=False )
        else:
            loge( f'Failed to drag any of {len(best)} options. Refresh already used. Trying blind drag' )
            input_mouse_drag( Vec2( 325, 250 ), Vec2( 325, 250+300 ), wait=2.0 )
    if has( 'mirror/mirror4/way/ThemePack/SelectFloor' ) and has( 'mirror/mirror4/way/ThemePack/ThemePack' ):
        raise TimeoutError( "Failed to find a valid theme, including randoming somehow" )

def mirror_choose_encounter_reward():
    if has( 'mirror/mirror4/way/RewardCard/FailedToChoose' ):
        loge( 'Got notice for failure to choose reward, canceling so we can try again' )
        click( 'mirror/mirror4/way/RewardCard/FailedToChooseCancel' )

    if click( 'mirror/mirror4/way/RewardCard/EGOGiftSpecCard', can_fail=True ):
        logd( 'Got ideal reward card; EGO Gift Spec' )
        press( 'ENTER' )
        click( 'mirror/mirror4/way/Confirm', can_fail=True ) # confirm ego
    elif click( 'mirror/mirror4/way/RewardCard/EGOGiftCard', can_fail=True ):
        press( 'ENTER' )
        click( 'mirror/mirror4/way/Confirm' ) # confirm ego
    elif click( 'mirror/mirror4/way/RewardCard/CostCard', can_fail=True ):
        press( 'ENTER' )
    elif click( 'mirror/mirror4/way/RewardCard/StarlightCard', can_fail=True ):
        press( 'ENTER' )
    elif click( 'mirror/mirror4/way/RewardCard/EGOResourceCard', can_fail=True ):
        press( 'ENTER' )
    else:
        raise TimeoutError( 'Failed to find valid reward card' )
        # alternatively, blindly press enter and hope for the best
        #press( 'ENTER' )
        #click( 'mirror/mirror4/way/Confirm', can_fail=True ) # confirm ego

def mirror_choose_ego_gift():
    click( 'mirror/mirror4/ego/egoGift' )
    click( 'mirror/mirror4/ego/SelectEGOGift' )

    logi( 'HUMAN trying new logic of verifying before pressing enter after ego gift' )
    sleep(1)
    if find( 'mirror/mirror4/ego/egoGift' ):
        loge( 'HUMAN EGO Gift required ENTER key' )
        press( 'ENTER' )

def mirror_starting_gifts():
    logd( 'Using Poise gift strategy' )
    click( 'mirror/mirror4/gift/Poise/Poise' )
    input_mouse_click( Vec2( 980, 280 ), wait=0.3 )
    input_mouse_click( Vec2( 980, 380 ), wait=0.3 )
    input_mouse_click( Vec2( 980, 480 ), wait=0.3 )
    input_mouse_click( Vec2( 1060, 600 ), wait=0.3 )
    press( 'ENTER' )

def mirror_route_floor( click_self_can_fail=False ):
    routes = {  'init.middle': Vec2(740, 340), 'init.high': Vec2(740,125), 'init.low': Vec2(740, 550),
                'midway.middle': Vec2(385, 340), 'midway.high': Vec2(385,100), 'midway.low': Vec2(385, 510),
                'boss.high': Vec2(720,200),
            } #TODO mid.high.y=100 seems too high? verify it works

    click( 'mirror/mirror4/way/Self', can_fail=click_self_can_fail )
    if find( 'mirror/mirror4/way/Enter' ):
        return press( 'ENTER', wait=2.0 )
    for name,pos in routes.items():
        logt( f'Attempting route {name}' )
        input_mouse_click( pos, wait=0.9 )
        if find( 'mirror/mirror4/way/Enter' ):
            logd( f'Routed via {name} @ {pos}' )
            return press( 'ENTER', wait=2.0 )
    else: raise TimeoutError( 'Failed to find valid route' )

def mirror_route_recovery_leave_return():
    loge( 'Attempting to leave and return to mirror run' )
    click( 'mirror/mirror4/way/CogWheel', timeout=1.0 )
    click( 'mirror/mirror4/way/ToWindow', timeout=1.0 )
    find( 'initMenu/drive', can_fail=False, timeout=5.0 )
def mirror_route_recovery_blind_spam():
    loge( 'Attempting to blindly click routes even without observing Self' )
    mirror_route_floor( click_self_can_fail=True )
def mirror_route_recovery_zoom_fix():
    loge( 'Attempting zoom fix (never works)' )
    # go out and in a bit to maybe scoot towards center, then go full out then in one step
    input_mouse_scroll( Vec2( win.size.x*90//100, win.size.y//2 ), 10, True )
    input_mouse_scroll( Vec2( win.size.x*90//100, win.size.y//2 ), 10, False )
    input_mouse_scroll( Vec2( win.size.x*90//100, win.size.y//2 ), 20, True )
    input_mouse_scroll( Vec2( win.size.x*90//100, win.size.y//2 ), 1, False )
    find( 'mirror/mirror4/way/Self', threshold=0.6, can_fail=False )
def mirror_route_recovery():
    try: return mirror_route_recovery_blind_spam()
    except TimeoutError: loge( 'Recovery method failed, trying next' )
    try: return mirror_route_recovery_zoom_fix()
    except TimeoutError: loge( 'Recovery method failed, trying next' )
    try: return mirror_route_recovery_leave_return()
    except TimeoutError: loge( "Recovery method failed, we're screwed" ); raise TimeoutError( 'Failed to recover via any method' )

def job_mirror( max_error_unknowns_count=10 ):
    logi( f'start' )
    st.stats_mirror_started += 1
    num_seen_floors = 0
    num_routed_nodes = 0
    error_zoom_count = 0
    error_unknowns_count = 0
    time_mirror_start = time.time()
    time_foor_start = time.time()

    st.stats_battle_rounds = 0
    st.stats_events_num = 0
    while not st.paused:
        reload_mod()
        should_reset_error_unknowns = True
        time_run_so_far = ( time.time() - time_mirror_start ) / 60 # minutes
        time_floor_so_far = ( time.time() - time_foor_start ) / 60 # minutes
        logd( f'{time_run_so_far:.1f}m. floor {num_seen_floors}/4. record {st.stats_mirror_successes}W-{st.stats_mirror_failures}L / {st.stats_mirror_started}' )

        if has( 'initMenu/drive' ):
            logd( 'Drive into mirror dungeon' )
            click( 'initMenu/drive' )
            click( 'mirror/mirror4/MirrorDungeons' )
            if find( 'mirror/previousClaimReward' ):
                logi( 'Prior run has rewards to claim' )
                press( 'ENTER' )
                if st.mirror_decline_previous_rewards:
                    logi( 'Declining previous run rewards' )
                    click( 'mirror/mirror4/GiveUpRewards' )
                else:
                    logi( 'Accepting previous run rewards' )
                    click( 'mirror/mirror4/ClaimRewardsStep2' )
                press( 'ENTER' )
                press( 'ENTER', wait=2.0 ) # acquire lunacy
                press( 'ENTER', wait=2.0 ) # pass level up (long animation)
        elif has( 'mirror/mirror4/mirror4Normal' ):
            logd( 'Enter MD normal' )
            click( 'mirror/mirror4/mirror4Normal' )
            if find( 'mirror/MirrorInProgress' ):
                logc( 'Blindly accepting mirror in progress. Please verify video log' )
                press( 'ENTER' )
                press( 'ENTER' )
            if click( 'mirror/mirror4/Enter', can_fail=True, wait=2 ) or click( 'mirror/mirror4/Resume', can_fail=True, wait=5 ):
                logd( 'Starting or resuming mirror' )
            else:
                raise TimeoutError( 'Failed to start or resume mirror' )
        elif has( 'mirror/mirror4/gift/Poise/Poise' ):
            logd( 'Choose starting gifts' )
            mirror_starting_gifts() if st.ai_starting_gifts else control_wait_for_human()
        elif detect_loading():
            logt( 'loading...' )
        elif has( 'mirror/mirror4/ClaimRewards' ):
            logi( 'Claiming final run rewards' )
            sleep( 6.0 ) # long wait for panels to advance (multiple seconds), numbers to animate, etc
            if mirror_result_judge( num_seen_floors ): # more floors seen increase odds of win but guarantee nothing
                logi( 'Win detected' )
                st.stats_mirror_successes += 1
                click( 'mirror/mirror4/ClaimRewards' ) # 85.7%
                click( 'mirror/mirror4/ClaimRewardsStep2' ) # 99.4%
            else:
                loge( 'Loss detected' )
                st.stats_mirror_failures += 1
                click( 'mirror/mirror4/ClaimRewards' ) # 85.7%
                if st.mirror_decline_partial_rewards:
                    loge( 'Declining rewards' )
                    click( 'mirror/mirror4/GiveUpRewards' ) # 89.8%
                else:
                    click( 'mirror/mirror4/ClaimRewardsStep2' ) # 99.4%

            press( 'ENTER' ) # popup to spend weekly
            press( 'ENTER', wait=2.0 ) # acquire lunacy
            press( 'ENTER', wait=2.0 ) # pass level up (long animation)

            log_stats( 'Run complete - stats', {
                'wins':st.stats_mirror_successes, 'losses':st.stats_mirror_failures, 'run time':f'{time_run_so_far:.1f}',
                'floor time':f'{time_floor_so_far:.1f}', 'floor':num_seen_floors, 'theme':st.current_floor_theme,
                'nodes':num_routed_nodes, 'events':st.stats_events_num,  'rounds':st.stats_battle_rounds,
                } )

            if find( 'initMenu/Window' ): break

            # in case of failure, spam enter and hope for the best
            for _ in range(5): press( 'ENTER' )
            if find( 'initMenu/Window' ): break

        elif has( 'mirror/mirror4/way/mirror4MapSign' ) and has( 'mirror/mirror4/way/Self', threshold=0.8 ):
            logd( 'Mirror floor routing' )
            num_routed_nodes += 1
            mirror_route_floor() if st.ai_routing else control_wait_for_human()
        elif has( 'mirror/mirror4/way/ThemePack/SelectFloor' ) and has( 'mirror/mirror4/way/ThemePack/ThemePack' ):
            num_seen_floors += 1
            logd( f'Selecting for floor {num_seen_floors}' )
            mirror_theme( num_seen_floors ) if st.ai_themes else control_wait_for_human()
            log_stats( 'New floor - stats', {
                'wins':st.stats_mirror_successes, 'losses':st.stats_mirror_failures, 'run time':f'{time_run_so_far:.1f}',
                'floor time':f'{time_floor_so_far:.1f}', 'floor':num_seen_floors, 'theme':st.current_floor_theme,
                'nodes':num_routed_nodes, 'events':st.stats_events_num,  'rounds':st.stats_battle_rounds,
                } )
            time_foor_start = time.time()
        elif has( 'event/Skip' ):
            logd( 'Event' )
            event_resolve()
        elif detect_battle_combat():
            logd( 'Battle combat' )
            battle_combat()
        elif has( 'team/Announcer', threshold=0.7 ) \
        and has( 'mirror/mirror4/firstTeamConfirm', threshold=0.6 ) \
        and not has( 'team/ClearSelection' ): # firstTeamConfirm was 0.5, 0.6 has false positives
            logd( 'Prepare initial team' )
            press( 'ENTER' ) if st.ai_team_select else control_wait_for_human()
        elif detect_battle_prepare():
            logd( 'Battle prepare' )
            battle_prepare_team( True ) if st.ai_team_select else control_wait_for_human()
        elif has( 'mirror/mirror4/way/RewardCard/RewardCardSign' ):
            logd( 'Choose reward card' )
            mirror_choose_encounter_reward() if st.ai_reward_cards else control_wait_for_human()
        elif has( 'mirror/mirror4/ego/egoGift' ):
            logd( 'Choose ego gift of multiple choices' )
            mirror_choose_ego_gift() if st.ai_reward_egos else control_wait_for_human()
        elif has( 'mirror/mirror4/way/Confirm' ):
            logd( 'Confirm what I think is an ego gift' )
            press( 'ENTER' )
        elif has( 'mirror/mirror4/way/Enter' ):
            logd( 'Assume in middle of accepting route node' )
            press( 'ESCAPE' )
        elif has( 'battle/confirm' ):
            logd( 'Assume post battle rewards confirm. Only should happen from crash' )
            click( 'battle/confirm' )
        elif has( 'mirror/mirror4/way/mirror4MapSign' ) and not has( 'mirror/mirror4/way/Self', threshold=0.8 ):
            loge( f'DANGER Assume in routing screen but with bad zoom or scroll. Seen {error_zoom_count} times' )
            error_zoom_count += 1
            if error_zoom_count > 3:
                logc( 'Too many errors, trying dangerous recovery attempts' )
                mirror_route_recovery()
                error_zoom_count = 0
        else:
            logw( f'Unknown state during mirror. Errors {error_unknowns_count}' )
            error_unknowns_count += 1
            should_reset_error_unknowns = False
            if error_unknowns_count > max_error_unknowns_count:
                raise TimeoutError( f'Too long in unknown state. Errors {error_unknowns_count}' )
        if should_reset_error_unknowns: error_unknowns_count = 0
        sleep(1.0)
    time_run_so_far = ( time.time() - time_mirror_start ) / 60 # minutes
    logd( f'end - {time_run_so_far:.1f}m. floor {num_seen_floors}/4. record {st.stats_mirror_successes}W-{st.stats_mirror_failures}L / {st.stats_mirror_started}' )

def job_resolve_until_home(): # True succeeded, False failed, None yieled for pause
    logi( 'start' )
    while not st.paused:
        if   click( 'initMenu/Window', can_fail=True, timeout=0.1 ): return True
        elif click( 'goBack/leftarrow', can_fail=True, timeout=0.1 ): pass
        elif click( 'initMenu/CloseMail', can_fail=True, timeout=0.1 ): pass
        elif click( 'initMenu/cancel', can_fail=True, timeout=0.1 ): pass
        elif detect_battle_prepare(): battle_prepare_team()
        elif detect_battle_combat(): battle_combat()
        elif detect_loading(): pass
        else: return False
        sleep(1.0)

def mirror_result_judge_panel() -> int|None:
    # Panel 0 actual is expected 1: 99% & 99%, 3: 63% & 85.9%
    # Panel 1 actual is expected 1: 55% & 99%, 3: 91% & 85.9%
    # Panel 2 actual is expected 1: 57% & 85.5%, 3: 99% & 98.4%
    panel = None
    if has_acc( 'mirror/mirror4/MirrorResultFirstPanelSign1' ) > 0.95 \
    and has_acc( 'mirror/mirror4/MirrorResultFirstPanelSign2' ) > 0.95:
        panel = 0
    if has_acc( 'mirror/mirror4/MirrorResultLastPanelSign1' ) > 0.95 \
    and has_acc( 'mirror/mirror4/MirrorResultLastPanelSign2' ) > 0.95:
        if panel is not None:
            loge( 'ERROR: both first and last panel detected' )
            panel = None
        else:
            panel = 2
    logd( f"panel {panel}" )
    return panel

def mirror_result_judge( timeout_for_last_panel=3.0 ) -> bool:
    logi( 'start' )
    # First we wait until we're on the last panel, or have timed out
    not_last_panel = False
    t0 = time.time()
    while mirror_result_judge_panel() != 2:
        time_spent_waiting = time.time() - t0
        if time_spent_waiting > timeout_for_last_panel:
            loge( "Failed to wait for last panel. Either we're stuck on the wrong panel or somewhere else entirely" )
            not_last_panel = True
            break
        logd( 'waiting for last panel...' )
        sleep(1.0)
    
    # Now look for various signs that are always the same on 100% completion runs
    # Actual 100% success is 99.6%+ for all signs
    possible_signs = 3 if not_last_panel else 4
    signs_of_success = 0
    if has_acc( 'mirror/mirror4/MirrorResultSuccessFull' ) > 0.96: signs_of_success += 1
    if has_acc( 'mirror/mirror4/MirrorResultSuccessBottom' ) > 0.96: signs_of_success += 1
    if has_acc( 'mirror/mirror4/MirrorResultSuccess100' ) > 0.96: signs_of_success += 1
    if has_acc( 'mirror/mirror4/MirrorResultSuccessPass30' ) > 0.96: signs_of_success += 1
    
    guess = signs_of_success >= (possible_signs-1) # 2/3, 3/4, or 4/4
    logi( f'signs {signs_of_success}/{possible_signs} -> guess {guess}' )
    return guess

def grind():
    logi( f'Grind run {st.stats_grind_runs_completed}/{st.stats_grind_runs_attempted}' )
    st.stats_grind_runs_attempted += 1
    step = 0
    while not st.paused:
        reload_mod()
        if step == 0:
            res = job_resolve_until_home()
            if res is None:
                logd( 'yielding for pause' )
                return
            elif res is True:
                logd( 'returned to home screen' )
                step = 0
            else:
                logw( 'Unable to resolve to home screen. Assuming mirror dungeon' )
                step = 6
        elif step == 1: job_stamina_buy_with_lunacy()
        elif step == 2: job_stamina_convert_to_modules()
        elif step == 3: job_claim_mail()
        elif step == 4: job_claim_battlepass()
        elif step == 5 and st.daily_exp_incomplete is True: job_daily_exp()
        elif step == 6 and st.daily_thread_incomplete is True: job_daily_thread()
        elif step == 7: job_mirror()
        elif step == 8: st.stats_grind_runs_completed += 1; break
        step += 1
        sleep(1.0)

################################################################################
## Bot universal / control
################################################################################

def report_status():
    print( st )
    print( f'Mouse: {input_mouse_get_pos()}' )

def control_toggle_pause():
    st.paused = not st.paused
    if st.paused: loge( 'Paused' )
    else:
        loge( 'Unpaused' )
        win_fix()

def control_halt():
    loge( 'Halting...' )
    st.halt = True
    st.paused = True # halt implies paused so we can simply check paused in loops

def control_wait_for_human():
    '''Waits for human to take care of something and press un-pause button (via hotkey thread)'''
    logc( '# Waiting for human intervention #' )
    st.paused = True
    while st.paused:
        sleep(0.3)

################################################################################
## Driver
################################################################################

def thread_main():
    keyboard.add_hotkey( 'home', control_toggle_pause )
    keyboard.add_hotkey( 'end', control_halt )
    keyboard.add_hotkey( 'page up', report_status )
    keyboard.add_hotkey( 'page down', discord_test )

    if st.ai_manual_override_routing: ai_set_manual_routing()

    logi( 'Starting grind loop' )
    while not st.halt:
        if not st.paused:
            reload_mod()
            try:
                grind()
            except TimeoutError as e:
                logc( f'Error: {e}. Desparation restart in 5 seconds' )
                sleep( 5.0 )
        sleep(0.1)
    loge( 'halting' )

def thread_video_log():
    if st.log_video is False: return
    fps = 30.0
    log_path = f'{st.log_directory}/video_{st.log_app_start_time}'
    fourcc = cv2.VideoWriter_fourcc( *"XVID" ) # mp4v .mp4 is much larger
    video = cv2.VideoWriter( f'{log_path}.avi', fourcc, fps, (win.size.x, win.size.y), isColor=True )
    logi( 'Starting video log' )
    try:
        while not st.halt:
            frame_start = time.time()

            screen_img = cv2.cvtColor( numpy.array(win_screenshot()), cv2.COLOR_RGB2BGR )
            video.write( screen_img )

            frame_time = time.time() - frame_start
            if frame_time < 1/fps:
                sleep( 1/fps - frame_time )
    finally:
        video.release()
    loge( 'halting' )

st = State()
win = Window()

def main():
    st.log_app_start_time = log_time()
    thread_cap = threading.Thread( target=thread_video_log )
    
    try:
        win_init()
        log_discord_clear()
        thread_cap.start()
        thread_main()
    except KeyboardInterrupt:
        loge( 'Killed by SIGINT' )
    except Exception as e:
        logc( f'Killed by unexpected: {e}' )
    finally:
        win_cleanup()
        st.halt = True
        thread_cap.join()