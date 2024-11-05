import ctypes
from   ctypes import windll
import ctypes.wintypes
import cv2
from   dataclasses import dataclass
import inspect
import keyboard
import numpy
import threading
import time
import win32api
import win32con
import win32gui

#FUTURE: remove pyautogui (no multi-monitor and bloated), win32gui, win32api, and keyboard
#FUTURE: record video of runs with cv2.VideoWriter and VideoWriter_fourcc, for debug

'''Known bugs
claim_battlepass: missed last mission. clicked too fast?
battle_prepare_team: incorrectly identifies 3/5 team as 5/5
battle_prepare_team: stuck with 1 character since meursault wasn't in list. verify working after fix
'''

MANUAL_OVERRIDE_ROUTING = True

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

def log( msg='', level=None ):
    # Derive meta information by crawling the stack
    thread, job, subjob = None, None, None
    for frame in inspect.stack():
        if thread is None and frame.function.startswith( 'thread_' ): thread = frame.function[6:]
        if job is None and frame.function.startswith( 'job_' ): job = frame.function[3:]
        if subjob is None and frame.function.startswith( 'subjob_' ): subjob = frame.function[6:]
    
    # Generate tag from meta info, then final text
    tag = '.'.join( x for x in [level,thread,job,subjob] if x )
    tag = f'[{tag}]'
    text = f'{tag} {msg}'

    # Colorized version for terminal output, based on log level
    text_colored = text
    if   level == 'CRITICAL': text_colored = log_colorize_text( text, 'Red' )
    elif level == 'ERROR':    text_colored = log_colorize_text( text, 'Red' )
    elif level == 'WARNING':  text_colored = log_colorize_text( text, 'Red' )
    elif level == 'INFO':     text_colored = log_colorize_text( text, 'Yellow' ) #Yellow Cyan Green Magenta
    elif level == 'DEBUG':    text_colored = log_colorize_text( text, 'Cyan' )
    elif level == 'TRACE':    text_colored = log_colorize_text( text, 'White' )

    # Print to terminal and write to log file
    print( text_colored )
    with open( f'logs/console_{st.log_app_start_time}.txt', 'a' ) as f:
        f.write( text +'\n' )

def logc( msg ): log( level='CRITICAL', msg=msg )
def logi( msg ): log( level='INFO', msg=msg )

@dataclass
class Vec2:
    x: int = 0
    y: int = 0

@dataclass
class Window:
    pos: Vec2 = Vec2(0,0)
    size: Vec2 = Vec2(1280,720)
    dpi: Vec2 = Vec2(144,144)

    hwnd: int = 0
    dc: int = 0
    screen_size: Vec2 = Vec2(0,0)

@dataclass
class State:
    daily_exp_incomplete: bool | None = None # None means unknown state
    daily_thread_incomplete: bool | None = None
    battle_team_type_mirror: bool = True
    paused: bool = False
    halt: bool = False

    job: str | None = None
    subjob: str | None = None

    ai_team_mirror_sinner_priority: list[int] = (2,3,10,0,8,5, 1,6,7,9,11,8)
    ai_team_lux_sinner_priority: list[int] = (2,3,10,0,1,5, 8,6,7,9,11,8)
    stamina_daily_resets: int = 9

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

    log_app_start_time: str = None
    log_video: bool = True

    stats_grind_runs: int = 0
    stats_mirror_successes: int = 0
    stats_mirror_failures: int = 0
    stats_stamina_resets: int = 0

win = Window()
st = State()

def win_init():
    '''Find window and normalize it'''
    win.hwnd = win32gui.FindWindow( "UnityWndClass", "LimbusCompany" )
    assert win.hwnd, 'Failed to find window handle'
    win.dc = windll.user32.GetDC( win.hwnd )
    assert win.dc, 'Failed to get window device context'
    win_fix()
    if win_verify(): raise Exception( 'Window DPI scaling or size is incorrect' )

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
    # Check DPI scaling
    dpi_x = windll.gdi32.GetDeviceCaps( win.dc, win32con.LOGPIXELSX ) # enums HORZRES DESKTOPHORZRES LOGPIXELSX
    dpi_y = windll.gdi32.GetDeviceCaps( win.dc, win32con.LOGPIXELSY )
    if win.dpi != Vec2(dpi_x,dpi_y): return f"Window DPI is {dpi_x},{dpi_y} instead of {win.dpi}"
    # Check window position and size
    x,y, width,height = win32gui.GetWindowRect( win.hwnd )
    if win.pos != Vec2(x,y): return f"Window position is {x},{y} instead of {win.pos}"
    if win.size != Vec2(width,height): return f"Window size is {width},{height} instead of {win.size}"

def win_screenshot():
    '''Take screenshot of window'''
    import pyautogui
    return pyautogui.screenshot( region=(win.pos.x,win.pos.y,win.size.x,win.size.y) )

def __input_mouse_click_PostMessage( pos: Vec2, button='left' ):
    '''Click mouse button at position. Not working for Limbus Company?'''
    # Use PostMessage to avoid stealing mouse from human user
    wParam = {'left':win32con.MK_LBUTTON, 'right':win32con.MK_RBUTTON}[button]
    lParam = pos.y<<16 | pos.x
    windll.user32.PostMessageA( win.hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0 )
    windll.user32.PostMessageA( win.hwnd, win32con.WM_LBUTTONDOWN, wParam, lParam )
    windll.user32.PostMessageA( win.hwnd, win32con.WM_LBUTTONUP, 0, lParam )

def sleep( seconds ):
    time.sleep( seconds )

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
        print( f'mouse dragging {pos}' )
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

################################################################################
## General image bot library
################################################################################

def img_find( template_name: str, threshold=0.8, use_best=True, use_grey_normalization=False, color_space=cv2.COLOR_RGB2GRAY ) -> Vec2 | None:
    # Load template image
    template_path = f'res/{template_name}.png'
    template_img = cv2.imread( template_path, cv2.IMREAD_GRAYSCALE )
    if template_img is None: raise FileNotFoundError( f'Failed to load template image {template_path}' )

    # Load screenshot image
    #TODO smart caching for performance reasons
    screen_img = cv2.cvtColor( numpy.array(win_screenshot()), color_space )

    if use_grey_normalization:
        clahe = cv2.createCLAHE( clipLimit=2.0, tileGridSize=(8,8) )
        template_img = clahe.apply( template_img )
        screen_img = clahe.apply( screen_img )
        

    # Find template in screenshot
    res = cv2.matchTemplate( screen_img, template_img, cv2.TM_CCOEFF_NORMED )

    loc = None
    if use_best:
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc( res )
        if max_val > threshold: loc = max_loc
        else: return
    else:
        locs = numpy.where( res >= threshold )
        if locs: loc = list(zip(*locs[::-1]))[0] # reverse x,y to y,x
        else: return
    
    # Find center of template at best match location
    h,w = template_img.shape
    center = Vec2( loc[0]+w//2, loc[1]+h//2 )
    print( f"    found {template_name} at {center}" )
    return center

def find( template_name: str, threshold=0.8, use_best=True, timeout=1.0, can_fail=True ):
    t0 = time.time()
    while time.time()-t0 < timeout:
        pos = img_find( template_name, threshold, use_best )
        if pos: return pos
        sleep(0.1)
    if not can_fail: raise TimeoutError( f"Failed to find {template_name} in {timeout} seconds" )
    return None

def has( template_name: str, threshold=0.8, use_best=True ):
    pos = img_find( template_name, threshold, use_best )
    return pos

def click( template_name: str, wait=0.6, can_fail=False, threshold=0.75, use_best=True, timeout=1.0 ):
    pos = find( template_name, threshold, use_best, timeout, can_fail )
    if pos: input_mouse_click( pos, wait )
    return pos

def nclick( template_name: str, wait=0.6, can_fail=False, threshold=0.75, use_best=True, timeout=1.0 ):
    '''Dry run version of click'''
    pos = find( template_name, threshold, use_best, timeout, can_fail )
    if pos: print( f"Would click {template_name} at {pos}" )
    return pos

def click_drag( template_name: str, dest_offset: Vec2, wait=0.9, can_fail=False, threshold=0.75, use_best=True, timeout=1.0 ):
    pos = find( template_name, threshold, use_best, timeout, can_fail )
    if pos: input_mouse_drag( pos, Vec2(pos.x+dest_offset.x, pos.y+dest_offset.y), wait )
    return pos

def press( key, wait=0.5 ):
    input_keyboard_press( key, wait )

################################################################################
## Bot universal
################################################################################

def report_status():
    print( st )
    print( 'Mouse', input_mouse_get_pos() )

def toggle_pause():
    st.paused = not st.paused
    if st.paused: print( 'Paused' )
    else:
        print( 'Unpaused' )
        win_fix()

def halt():
    print( 'Halting...' )
    st.paused = True
    st.halt = True

def wait_for_human():
    '''Waits for human to take care of something and press un-pause button (via hotkey thread)'''
    print( '>>> Waiting for human intervention <<<' )
    st.paused = True
    while st.paused:
        sleep(0.1)

################################################################################
## Limbus Specific
################################################################################

def detect_battle_prepare() -> bool:
    return has( 'team/Announcer', threshold=0.7 )
def detect_loading() -> bool:
    return has( 'CombatTips' ) or has( 'Wait' )
def detect_battle_combat() -> bool:
    return has( 'battle/WinRate' ) or has( 'battle/Start' )

def stamina_convert_to_modules():
    print( '[Main] Job - stamina_convert_to_modules' )
    click( 'initMenu/greenPai' )
    click( 'initMenu/maxModule' )
    click( 'initMenu/confirm' )
    click( 'initMenu/cancel', can_fail=True )

def stamina_buy_with_lunacy():
    print( '[Main] Job - stamina_buy_with_lunacy' )
    click( 'initMenu/greenPai' )
    click( 'initMenu/UseLunary' )
    # old safe strat was just 1/d by looking for first buy image
    # now we do less safe N/day strat by looking for N+1 reset imagery
    #if find( 'initMenu/FirstBuy', threshold=0.9 ):
    if not find( f'initMenu/StaminaReset{st.stamina_daily_resets}' ):
        click( 'initMenu/confirm' )
        st.stats_stamina_resets += 1
    else:
        print( f'Already bought {st.stamina_daily_resets} resets today' )
    click( 'initMenu/cancel', can_fail=True )

def claim_mail():
    print( '[Main] Job - claim_mail' )
    click( 'initMenu/window' )
    click( 'initMenu/Mail' )
    click( 'initMenu/ClaimAll' )
    click( 'initMenu/MailConfirm', can_fail=True )
    click( 'initMenu/CloseMail' )

def claim_battlepass():
    print( '[Main] Job - claim_battlepass' )
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
    click( 'prize/Weekly' )
    pos = Vec2(520,240)
    for i in range(5):
        input_mouse_click( pos )
        pos.y += 90
    click( 'goBack/leftarrow' )

def daily_exp():
    print( '[Main] Job - daily_exp' )
    click( 'initMenu/drive' )
    for _ in range(5):
        click( 'luxcavation/luxcavationEntrance' )
        if find( 'luxcavation/ExpEntrance' ): break
    else: raise TimeoutError( 'Failed to find luxcavation entrance' )
    click( 'luxcavation/ExpEntrance' )
    click( 'luxcavation/EXPDifficultyLv18' )
    find( 'team/Announcer', threshold=0.7, timeout=3.0, can_fail=False )
    battle_prepare_team()
    battle_combat()
    click( 'goBack/leftarrow' )

def daily_thread():
    print( '[Main] Job - daily_thread' )
    click( 'initMenu/drive' )
    for _ in range(5):
        click( 'luxcavation/luxcavationEntrance' )
        if find( 'luxcavation/ThreadEntrance' ): break
    else: raise TimeoutError( 'Failed to find luxcavation entrance' )
    click( 'luxcavation/ThreadEntrance' )
    click( 'luxcavation/Enter' )
    click( 'luxcavation/ThreadDifficultyLv20' )
    find( 'team/Announcer', threshold=0.7, timeout=3.0, can_fail=False )
    battle_prepare_team()
    battle_combat()
    click( 'goBack/leftarrow' )

def battle_prepare_team( battle_load_timeout=None ):
    print( '[Main] SubJob - battle_prepare_team' )
    # Choose team order
    sinner_priority_list = st.ai_team_mirror_sinner_priority if st.battle_team_type_mirror else st.ai_team_lux_sinner_priority
    full_template = 'team/FullTeam66' if st.battle_team_type_mirror else 'team/FullTeam55'
    if not find( full_template, threshold=0.95 ):
        click( 'team/ClearSelection', wait=0.8 )
        press( 'ENTER' )
        pos = find( 'team/Announcer', threshold=0.7, can_fail=False )
        for idx in sinner_priority_list:
            rel_pos = Vec2( (idx % 6 +1)* 140, (idx//6)*200 + 100 )
            input_mouse_click( Vec2(pos.x+rel_pos.x, pos.y+rel_pos.y) )
    else:
        print( 'Team is already prepared' )

    # Now start battle
    press( 'ENTER' )

    # Wait for battle to load
    time_last_seen_loading = time.time()
    while not detect_battle_combat() and not st.paused:
        if detect_loading():
            time_last_seen_loading = time.time()
            print( 'Battle is loading...' )
        if battle_load_timeout is not None and (time.time()-time_last_seen_loading > battle_load_timeout):
            raise TimeoutError( 'Failed to load battle' )
        sleep(1.0)
    
    print( 'Battle is loaded' )

def battle_combat( battle_state_unknown_timeout=5 ):
    print( '[Main] SubJob - battle_combat' )
    error_count = 0
    while not st.paused:
        # Regular combat
        if detect_battle_combat():
            print( 'Battle awaiting player commands. Trying winrate' )
            press( 'p' )
            press( 'ENTER' )
            if click( 'battle/WinRate', can_fail=True ):
                press( 'ENTER' )
            error_count = 0
        elif has( 'battle/battlePause' ):
            print( 'Battle animation in progress' )
            error_count = 0
        elif detect_loading():
            print( 'Loading...' )
            error_count = 0
        # Battle interuptions (like events)
        elif has( 'event/Skip' ):
            event_resolve()
            error_count = 0
        # Unclear
        elif not has( 'mirror/mirror4/way/mirror4MapSign' ) and has( 'battle/trianglePause' ):
            print( 'JMR unclear state but other bot checks for this and hits the play button' )
            click( 'battle/trianglePause' )
            if st.stop_for_inspecting_unknowns:
                wait_for_human() #FIXME: figure out what this is for
            error_count = 0
        # End of battle
        elif has( 'battle/levelUpConfirm' ):
            print( 'End of battle level up' )
            click( 'battle/levelUpConfirm' )
        elif has( 'battle/blackWordConfirm' ) or has( 'battle/confirm' ):
            print( 'End of battle confirm' )
            click( 'battle/blackWordConfirm', can_fail=True ) or click( 'battle/confirm' )
            break
        elif has( 'mirror/mirror4/way/RewardCard/RewardCardSign' ):
            print( 'End of battle reward card' )
            break
        elif has( 'mirror/mirror4/ego/egoGift' ):
            print( 'End of battle ego gift' )
            break
        elif has( 'mirror/mirror4/way/mirror4MapSign' ):
            print( 'Battle ended without fanfare' )
            break
        # Unknown state / error handling
        else:
            print( 'Battle state unknown' ) # usualy minor animation for new wave or animating reward screen
            if error_count > battle_state_unknown_timeout:
                raise TimeoutError( 'Battle state unknown for too long' )
            error_count += 1
        sleep(1.0)

def mirror_shop_chair():
    # Attempt to aoe heal
    if find( 'mirror/mirror4/ProductCatalogue/ChairHealSinner' ):
        click( 'mirror/mirror4/ProductCatalogue/ChairHealSinner' )
        click( 'mirror/mirror4/ProductCatalogue/AllSinnerRest' )
        click( 'event/Skip' )
        click( 'event/Skip' )
        if not click( 'event/Continue', can_fail=True ):
            click( 'mirror/mirror4/ProductCatalogue/DontPurchase' )
    
    #FUTURE: fuse certain combos
    
    # Leave so event handler doesn't get stuck in loop
    click( 'event/Leave' )
    click( 'mirror/mirror4/whiteConfirm' )

def mirror_shop_buy():
    # Attempt to aoe heal
    if find( 'mirror/mirror4/ProductCatalogue/ChairHealSinner' ):
        click( 'mirror/mirror4/ProductCatalogue/ChairHealSinner' )
        click( 'mirror/mirror4/ProductCatalogue/AllSinnerRest' )
        click( 'event/Skip' )
        if not click( 'event/Continue', can_fail=True ):
            click( 'mirror/mirror4/ProductCatalogue/DontPurchase' )
    
    # Attempt to buy egos with remaining cash
    ego_locs = [ Vec2(930,350), Vec2(1130,350), Vec2(780,450), Vec2(930,450), Vec2(1130,450) ]
    for ego_loc in ego_locs:
        input_mouse_click( ego_loc )
        if click( 'mirror/mirror4/ProductCatalogue/ConfirmPurchase', can_fail=True ):
            click( 'mirror/mirror4/way/Confirm' )
    
    # Leave so event handler doesn't get stuck in loop
    click( 'event/Leave' )
    click( 'mirror/mirror4/whiteConfirm' )

def event_choice( choice: int ): # choice slot 0..2
    pos = has( 'event/Skip' )
    if pos:
        input_mouse_click( Vec2(pos.x+150, pos.y -100 +choice*100), wait=1.5 )

def event_resolve( max_skip_attempts=10 ):
    print( '[Main] SubJob - event_resolve' )
    if not st.ai_events:
        print( 'HUMAN Handle event' )
        return wait_for_human()
    skip_attempts = 0
    while not st.paused:
        if has( 'mirror/mirror4/ProductCatalogue/ProductCatalogue' ):
            if has( 'mirror/mirror4/ProductCatalogue/FuseGifts' ):
                print( 'Event is a shop (chair)' )
                mirror_shop_chair() if st.ai_shop_chair else wait_for_human()
            elif has( 'mirror/mirror4/ProductCatalogue/PurchaseEGO' ):
                print( 'Event is a shop (buy)' )
                mirror_shop_buy() if st.ai_shop_buy else wait_for_human()
            break
        elif has( 'event/ChooseCheck' ):
            print( 'Event choose sinner to perform check' )
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
            print( 'Event over' )
            has( 'event/Continue' ) and click( 'event/Continue' )
            has( 'event/Proceed' ) and click( 'event/Proceed' )
            has( 'event/ToBattle' ) and click( 'event/ToBattle' )
            has( 'event/CommenceBattle' ) and click( 'event/CommenceBattle' )
            break
        elif has( 'event/Leave' ):
            print( 'Event leave' )
            click( 'event/Leave' )
            click( 'mirror/mirror4/whiteConfirm' )
            break
        elif has( 'event/Choices' ):
            print( 'Event bespoke choices' )
            #FIXME fragile? maybe increase threshold. or exepct false positives?
            # "Result" from Continue/Proceed and even some Skips gets interpretted as "Choices" banner
            if has( 'encounter/UnDeadMechine1', threshold=0.9 ):
                event_choice(1)
            elif has( 'encounter/UnDeadMechine2', threshold=0.9 ):
                event_choice(2)
            elif has( 'encounter/PinkShoes', threshold=0.9 ):
                event_choice(2)
            elif has( 'encounter/RedKillClock', threshold=0.9 ):
                event_choice(1)
                event_choice(2)
            else:
                event_choice(2)
                event_choice(1)
            #skip_attempts = 0
        elif has( 'event/Skip' ):
            print( f'Event attempting skip. Try {skip_attempts}' )
            click( 'event/Skip' )
            click( 'event/PassToGainEGO', can_fail=True )
            click( 'event/EGOGiftChoice', can_fail=True )
            skip_attempts += 1
        else:
            print( 'Unknown event state' )
            skip_attempts += 1
        if skip_attempts > max_skip_attempts:
                raise TimeoutError( 'Event exceeded max skip attempts. Must be stuck' )
        sleep(1.0)

def mirror_theme():
    for i in range(2):
        if find( 'mirror/mirror4/theme/EventTheme' ):
            print('Found event theme')
            return click_drag( 'mirror/mirror4/theme/EventTheme', Vec2(0,300) )
        for i in range(1,41+1):
            if st.paused: return
            template= f'mirror/mirror4/theme/{i}'
            if find( template, timeout=0.1 ):
                print( f'Found theme {i}' )
                return click_drag( template, Vec2(0,300) )
            print( f'..theme {i} not found' )
        if i == 0: click( 'mirror/mirror4/theme/refresh' )

    print( 'Attemping last ditch efforts to find a theme' )
    #if click( 'mirror/mirror4/theme/LBIcon', can_fail=True ): return # removed due to false positives

    input_mouse_drag( Vec2( 325, 250 ), Vec2( 325, 250+300 ), wait=2.0 )
    if has( 'mirror/mirror4/way/ThemePack/SelectFloor' ) and has( 'mirror/mirror4/way/ThemePack/ThemePack' ):
        raise TimeoutError( "Failed to find a valid theme, including randoming somehow" )

def mirror_route_floor():
    routes = { 'init.middle': Vec2(740, 340), 'init.high': Vec2(740,125), 'init.low': Vec2(740, 550),
                   'midway.middle': Vec2(385, 340), 'midway.high': Vec2(385,100), 'midway.low': Vec2(385, 510) }

    click( 'mirror/mirror4/way/Self' )
    if find( 'mirror/mirror4/way/Enter' ):
        return press( 'ENTER', wait=2.0 )
    for name,pos in routes.items():
        print( f'Attempting route {name}' )
        input_mouse_click( pos, wait=0.9 )
        if find( 'mirror/mirror4/way/Enter' ): return press( 'ENTER', wait=2.0 )
    else: raise TimeoutError( 'Failed to find valid route' )

def mirror_choose_encounter_reward():
    if click( 'mirror/mirror4/way/RewardCard/EGOGiftSpecCard', can_fail=True ):
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
    press( 'ENTER' )

def mirror_starting_gifts():
    click( 'mirror/mirror4/gift/Poise/Poise' )
    input_mouse_click( Vec2( 980, 280 ), wait=0.3 )
    input_mouse_click( Vec2( 980, 380 ), wait=0.3 )
    input_mouse_click( Vec2( 980, 480 ), wait=0.3 )
    input_mouse_click( Vec2( 1060, 600 ), wait=0.3 )
    press( 'ENTER' )

def mirror_dungeon():
    print( '[Main] Job - mirror_dungeon' )
    error_zoom_count = 0
    while not st.paused:
        if has( 'initMenu/drive' ):
            print( 'Drive into mirror dungeon' )
            click( 'initMenu/drive' )
            click( 'mirror/mirror4/MirrorDungeons' )
            if find( 'mirror/previousClaimReward' ):
                print( 'HUMAN There is a reward from a pre-existing session. Please handle manually' )
                wait_for_human()
        elif has( 'mirror/mirror4/mirror4Normal' ):
            print( 'Enter MD normal' )
            click( 'mirror/mirror4/mirror4Normal' )
            if find( 'mirror/MirrorInProgress' ):
                print( 'HUMAN Mirror is in progress. Please handle manually' )
                wait_for_human()
            if click( 'mirror/mirror4/Enter', can_fail=True, wait=2 ) or click( 'mirror/mirror4/Resume', can_fail=True, wait=5 ):
                print( 'Starting or resuming mirror' )
            else:
                raise TimeoutError( 'Failed to start or resume mirror' )
        elif has( 'mirror/mirror4/gift/Poise/Poise' ):
            print( 'Choose starting gifts' )
            mirror_starting_gifts() if st.ai_starting_gifts else wait_for_human()
        elif detect_loading():
            print( 'Loading...' )
        elif has( 'mirror/mirror4/ClaimRewards' ):
            print( 'Claiming final run rewards' )
            print( 'HUMAN please gather images for win vs loss detection' )
            wait_for_human()
            press( 'ENTER' ) # first claim rewards button
            press( 'ENTER' ) # box to spend modules #TODO probably check this for Win v Loss and option to decline
            press( 'ENTER' ) # popup to spend weekly
            press( 'ENTER', wait=2.0 ) # acquire lunacy
            press( 'ENTER', wait=2.0 ) # pass level up (long animation)
            if find( 'initMenu/Window' ): break
        elif has( 'mirror/mirror4/way/mirror4MapSign' ) and has( 'mirror/mirror4/way/Self', threshold=0.8 ):
            print( 'Mirror floor routing' )
            mirror_route_floor() if st.ai_routing else wait_for_human()
        elif has( 'mirror/mirror4/way/ThemePack/SelectFloor' ) and has( 'mirror/mirror4/way/ThemePack/ThemePack' ):
            print( 'Selecting floor' )
            mirror_theme() if st.ai_themes else wait_for_human()
        elif has( 'event/Skip' ):
            print( 'Event in progress' )
            event_resolve()
        elif detect_battle_combat():
            print( 'Battle in progress' )
            battle_combat()
        elif has( 'team/Announcer', threshold=0.7 ) \
        and has( 'mirror/mirror4/firstTeamConfirm', threshold=0.6 ) \
        and not has( 'team/ClearSelection' ): # firstTeamConfirm was 0.5, 0.6 has false positives
            print( 'Confirming initial team' )
            press( 'ENTER' ) if st.ai_team_select else wait_for_human()
        elif detect_battle_prepare():
            print( 'Battle preparation' )
            battle_prepare_team() if st.ai_team_select else wait_for_human()
        elif has( 'mirror/mirror4/way/RewardCard/RewardCardSign' ):
            print( 'Choose reward card' )
            mirror_choose_encounter_reward() if st.ai_reward_cards else wait_for_human()
        elif has( 'mirror/mirror4/ego/egoGift' ):
            print( 'Choosing ego gift of multiple choices' )
            mirror_choose_ego_gift() if st.ai_reward_egos else wait_for_human()
        elif has( 'mirror/mirror4/way/Confirm' ):
            print( 'Confirming what I think is an ego gift' )
            press( 'ENTER' )
        elif has( 'mirror/mirror4/way/Enter' ):
            print( 'Assume in middle of accepting route node' )
            press( 'ESCAPE' )
        elif has( 'battle/confirm' ):
            print( 'Assume post battle rewards confirm. Only should happen from crash' )
            click( 'battle/confirm' )
        elif has( 'mirror/mirror4/way/mirror4MapSign' ) and not has( 'mirror/mirror4/way/Self', threshold=0.8 ):
            print( f'DANGER Assume in routing screen with bad zoom or scroll. Seen {error_zoom_count} times' )
            error_zoom_count += 1
            if error_zoom_count > 3:
                print( 'DANGER Attempting to fix zoom. This rarely works' )
                input_mouse_scroll( Vec2( win.size.x*90//100, win.size.y//2 ), 10, True )
                input_mouse_scroll( Vec2( win.size.x*90//100, win.size.y//2 ), 10, False )
                input_mouse_scroll( Vec2( win.size.x*90//100, win.size.y//2 ), 20, True )
                # scroll back in one step then hail mary for Self template
                input_mouse_scroll( Vec2( win.size.x*90//100, win.size.y//2 ), 1, False )
                if find( 'mirror/mirror4/way/Self', threshold=0.5 ):
                    print( 'Chance we recovered?' )
                else:
                    raise TimeoutError( 'Bad route zoom or positioning. Need better fix strategy' )
                # ? consider cog wheel > to window > then resume the run?
        else:
            print( 'Unknown state during mirror' )
        sleep(1.0)

def resolve_until_home():
    print( '[Main] SubJob - resolve_until_home' )
    while not st.paused:
        if click( 'initMenu/Window', can_fail=True, timeout=0.1 ): return True
        elif click( 'goBack/leftarrow', can_fail=True, timeout=0.1 ): pass
        elif click( 'initMenu/CloseMail', can_fail=True, timeout=0.1 ): pass
        elif click( 'initMenu/cancel', can_fail=True, timeout=0.1 ): pass
        elif detect_battle_prepare(): battle_prepare_team()
        elif detect_battle_combat(): battle_combat()
        elif detect_loading(): pass
        else: return False
        sleep(1.0)

def grind():
    if st.paused: return
    logi( 'Grind run' )

    raise NotImplementedError( 'Grind not implemented' )
    if resolve_until_home() == False:
        print( 'Unable to resolve to home screen. Assuming mirror dungeon' )
        return mirror_dungeon()

    stamina_convert_to_modules()
    if st.paused: return
    stamina_buy_with_lunacy()
    if st.paused: return
    claim_mail()
    if st.paused: return
    claim_battlepass()
    if st.paused: return
    if st.daily_exp_incomplete is True: daily_exp()
    if st.paused: return
    if st.daily_thread_incomplete is True: daily_thread()
    if st.paused: return
    mirror_dungeon()

    st.stats_grind_runs += 1

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

def thread_main():
    keyboard.add_hotkey( 'pause', toggle_pause )
    keyboard.add_hotkey( 'scroll lock', halt )
    keyboard.add_hotkey( 'home', report_status )

    if MANUAL_OVERRIDE_ROUTING: ai_set_manual_routing()

    logi( 'Starting grind loop' )
    while not st.halt:
        grind()
        sleep(0.1)
    logc( 'halting' )

################################################################################
## Driver
################################################################################

def thread_video_log():
    if st.log_video is False: return
    fps = 30.0
    log_path = f'logs/video_{st.log_app_start_time}'
    if 1:
        fourcc = cv2.VideoWriter_fourcc( *"XVID" )
        video = cv2.VideoWriter( f'{log_path}.avi', fourcc, fps, (win.size.x, win.size.y), isColor=True )
    else:
        fourcc = cv2.VideoWriter_fourcc( *"mp4v" ) # alternatively, hev1 h264 XVID
        video = cv2.VideoWriter( f'{log_path}.mp4', fourcc, fps, (win.size.x, win.size.y), isColor=True )
    frame_count = 0
    logi( 'Starting video log' )
    try:
        while not st.halt:
            frame_start = time.time()
            frame_count += 1

            screen_img = cv2.cvtColor( numpy.array(win_screenshot()), cv2.COLOR_RGB2BGR )
            video.write( screen_img )

            frame_time = time.time() - frame_start
            if frame_time < 1/fps:
                sleep( 1/fps - frame_time )
    finally:
        video.release()
        #cv2.destroyAllWindows()
    logc( 'halting' )

def main():
    st.log_app_start_time = log_time()
    thread_cap = threading.Thread( target=thread_video_log )
    try:
        win_init()
        thread_cap.start()
        thread_main()
    finally:
        win_cleanup()
        st.halt = True
        thread_cap.join()

if __name__ == '__main__': main()