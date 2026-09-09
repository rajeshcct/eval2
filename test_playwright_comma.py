from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.set_content('''
        <div>
            <textarea style="display:none;"></textarea>
            <input placeholder="message" />
        </div>
    ''')
    
    sel = 'textarea, input[placeholder*="message" i]'
    print('Count:', page.locator(sel).count())
    print('First visible:', page.locator(sel).first.is_visible())
    
    visible_sel = f'{sel} >> visible=true >> nth=0'
    print('Visible count:', page.locator(visible_sel).count())
    browser.close()
