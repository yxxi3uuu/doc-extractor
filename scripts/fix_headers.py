import os, re, glob, sys

WORK_DIR = os.path.dirname(os.path.abspath(__file__))


if __name__ == "__main__":
    pattern = os.path.join(WORK_DIR, '2026*_kw_kw.txt')
    txt_files = sorted(glob.glob(pattern))
    print('found ' + str(len(txt_files)) + ' files', flush=True)

    fixed = 0
    for txt_path in txt_files:
        with open(txt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # find first article marker
        first_art = content.find('■ [1]')
        if first_art == -1:
            continue
        
        # count articles
        art_count = len(re.findall(r'■\s*\[\d+\]', content))
        
        # rebuild with clean header
        fname = os.path.basename(txt_path)
        base = fname.replace('_kw_kw.txt', '_kw.txt')
        clean_content = base + '\n' + '共 ' + str(art_count) + ' 篇文章\n\n' + content[first_art:]
        
        if content != clean_content:
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(clean_content)
            fixed += 1

    print('fixed ' + str(fixed) + ' files', flush=True)
