"""Synthetic UI frames contain no customer data and run without a desktop."""
import pytest
from PIL import Image, ImageDraw

from wxbot.wecom_layout import detect_wecom_layout


def frame(scale=1, sidebar=True, width=1200, height=900):
    px = lambda x: round(x*scale)
    w, h = px(width), px(height)
    nav, left = px(60), px(310)
    right = w-px(300) if sidebar else w
    header, editor = px(64), h-px(154)
    im = Image.new('RGB', (w,h), (245,247,250))
    d = ImageDraw.Draw(im)
    d.rectangle((0,0,nav-1,h), fill=(215,230,240))
    d.rectangle((nav,0,left-1,h), fill=(240,243,247))
    d.line((nav-1,0,nav-1,h), fill=(207,219,229))
    d.line((left-1,0,left-1,h), fill=(223,225,226))
    d.line((left,header-1,w,header-1), fill=(228,231,234))
    if sidebar:
        d.rectangle((right,header,w,h),fill=(246,246,247))
        d.line((right-1,header,right-1,h),fill=(228,231,234))
    d.rectangle((left+px(16),editor,right-px(16)-1,h-px(17)-1),fill='white')
    anchors = []
    for n in range(6):
        top=px(75+n*63)
        if n==2:
            d.rectangle((nav+px(3),top-px(10),left-px(3),top+px(50)),fill=(72,144,249))
        d.rectangle((nav+px(16),top,nav+px(56)-1,top+px(40)-1),fill=(80,100,120))
        anchors.append(top+px(4))
    return im, (nav,left,right,header,editor), anchors


@pytest.mark.parametrize('scale',[.75,1,1.25,1.5,2])
@pytest.mark.parametrize('sidebar',[True,False])
@pytest.mark.parametrize('width,height',[(1200,900),(1800,1100),(1000,700)])
def test_geometry_and_rows_across_scale_size_and_sidebar(scale,sidebar,width,height):
    im, expected, rows=frame(scale,sidebar,width,height)
    layout=detect_wecom_layout(im)
    assert layout is not None
    for actual, wanted in zip((layout.nav_right,layout.chat_left,layout.chat_right,
                                layout.header_bottom,layout.input_top), expected):
        assert abs(actual-wanted) <= 3
    got=layout.rows(im.crop((layout.nav_right,0,layout.chat_left,im.height)))
    assert len(got)==len(rows)
    assert all(abs(x-y)<=3 for x,y in zip(got,rows))


@pytest.mark.parametrize('colour',['white','black',(245,247,250)])
def test_empty_login_or_unrendered_frame_is_rejected(colour):
    assert detect_wecom_layout(Image.new('RGB',(1200,900),colour)) is None


def test_partial_dialog_covering_editor_is_rejected():
    im,_,_=frame()
    ImageDraw.Draw(im).rectangle((350,400,800,899),fill=(210,210,210))
    assert detect_wecom_layout(im) is None


def test_runtime_remeasures_and_never_reuses_failed_geometry(monkeypatch):
    from wxbot.scanner import Scanner
    s=Scanner({'layout':{'auto_detect':True}})
    im,_,_=frame()
    current=[im]
    monkeypatch.setattr(s,'get_region',lambda:(10,20,*current[0].size))
    monkeypatch.setattr(s,'_grab_window_cached',lambda:current[0])
    assert s.get_col2_region()==(70,20,250,900)
    assert s.get_col3_region()==(320,20,589,900)
    # Same-sized sidebar change, then resize (no waiting for an old cache).
    current[0]=frame(sidebar=False)[0]
    s._layout_checked=0
    assert s.get_col3_region()[2]==890
    current[0]=frame(scale=1.5)[0]
    assert s.get_col2_region()==(100,20,375,1350)
    current[0]=Image.new('RGB',current[0].size,'white')
    s._layout_checked=0
    assert s.get_col2_region() is None
    assert s._auto_layout is None
    clicks=[]
    monkeypatch.setattr(s,'click_position',lambda *a:clicks.append(a))
    assert s.click_input_box() is False
    assert not clicks


def test_input_click_stays_inside_detected_editor(monkeypatch):
    from wxbot.scanner import Scanner
    s=Scanner({'layout':{'auto_detect':True}})
    im,_,_=frame(scale=2)
    monkeypatch.setattr(s,'get_region',lambda:(100,200,*im.size))
    monkeypatch.setattr(s,'_grab_window_cached',lambda:im)
    clicks=[]
    monkeypatch.setattr(s,'click_position',lambda *a:clicks.append(a))
    assert s.click_input_box()
    x,y=clicks[0]; l=s._auto_layout
    assert 100+l.chat_left < x < 100+l.chat_right
    assert 200+l.input_top < y < 200+l.input_bottom


def test_failed_editor_detection_blocks_keyboard_and_clipboard(monkeypatch):
    from wxbot.scanner import Scanner
    import wxbot.scanner as module
    s=Scanner({'layout':{'auto_detect':True}})
    monkeypatch.setattr(s,'click_input_box',lambda:False)
    clipboard=[]; keys=[]
    monkeypatch.setattr(s,'_set_clipboard',lambda text:clipboard.append(text))
    monkeypatch.setattr(module.pyautogui,'hotkey',lambda *a:keys.append(a))
    monkeypatch.setattr(module.pyautogui,'press',lambda *a:keys.append(a))
    with pytest.raises(RuntimeError):
        s.send_message_via_keyboard('must not be sent')
    assert not clipboard and not keys


def test_switching_away_from_wecom_clears_auto_detection():
    from wxbot.profile import apply_to_config, load_profile
    cfg=apply_to_config({},load_profile('wecom'))
    assert cfg['layout']['auto_detect']
    other=apply_to_config(cfg,load_profile('wechat_pc'))
    assert other['layout']['auto_detect'] is False


def test_manual_mode_keeps_existing_coordinate_configuration(monkeypatch):
    from wxbot.scanner import Scanner
    s=Scanner({'columns':{'col1_width_px':90,'col2_width_px':360}})
    monkeypatch.setattr(s,'get_region',lambda:(20,30,1600,1000))
    monkeypatch.setattr(s,'_grab_window_cached',lambda:pytest.fail('manual mode must not detect'))
    assert s.get_col2_region()==(110,30,360,1000)


def test_title_ocr_uses_full_header_instead_of_list_row_crop(monkeypatch):
    from wxbot.scanner import Scanner
    from wxbot.detector import MessageDetector
    s=Scanner({'layout':{'auto_detect':True}})
    im,_,_=frame()
    monkeypatch.setattr(s,'get_region',lambda:(0,0,*im.size))
    monkeypatch.setattr(s,'_grab_window_cached',lambda:im)
    monkeypatch.setattr(s,'capture_region',lambda x,y,w,h:im.crop((x,y,x+w,y+h)))
    d=MessageDetector({'state_dir':'unused'})
    seen=[]
    def full_text(img,**kwargs):
        seen.append(img.size)
        return 'Short contact'
    monkeypatch.setattr(d,'extract_text',full_text)
    monkeypatch.setattr(d,'detect_name_region',lambda img:pytest.fail('not a list row'))
    assert s.verify_open('Short contact',d.read_row_name)
    assert seen==[(589,64)]


def test_runtime_recovers_without_writing_shared_config(monkeypatch):
    from wxbot.scanner import Scanner
    cfg={'layout':{'auto_detect':True},'columns':{'col1_width_px':3,'col2_width_px':4}}
    s=Scanner(cfg)
    current=[Image.new('RGB',(1200,900),'black')]
    monkeypatch.setattr(s,'get_region',lambda:(0,0,*current[0].size))
    monkeypatch.setattr(s,'_grab_window_cached',lambda:current[0])
    assert s.get_col2_region() is None
    current[0]=frame()[0];s._layout_checked=0
    assert s.get_col2_region()==(60,0,250,900)
    assert cfg['columns']=={'col1_width_px':3,'col2_width_px':4}


def test_fallback_scans_detected_rows_instead_of_static_row_count(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock
    import main
    from wxbot.scanner import Scanner
    cfg={'layout':{'auto_detect':True},'fallback':{'max_scan_rows':1}}
    s=Scanner(cfg);im,_,rows=frame()
    monkeypatch.setattr(s,'get_region',lambda:(0,0,*im.size))
    monkeypatch.setattr(s,'_grab_window_cached',lambda:im)
    monkeypatch.setattr(s,'capture_region',lambda x,y,w,h:im.crop((x,y,x+w,y+h)))
    clicks=[]
    monkeypatch.setattr(s,'click_col2_row',lambda y:clicks.append(y))
    detector=MagicMock()
    detector.read_row_name.return_value=(Image.new('RGB',(20,20)),'internal contact')
    detector.is_customer_name.return_value=False
    result=asyncio.run(main._scan_fallback(s,detector,cfg))
    assert result==(False,'',None,[])
    assert detector.read_row_name.call_count==len(rows)
    assert not clicks
