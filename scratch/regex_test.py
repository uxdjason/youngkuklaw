import re
text = "Here is [R (Jackson) v A-G [2005]](/r-jackson-v-a-g) and [rule of law](/r-jackson) and [Something](http://google.com)"
pattern = re.compile(r'\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(([^)\s]+)\)')
for m in pattern.finditer(text):
    print("Match:", m.group(0))
    print("Text:", m.group(1))
    print("URL:", m.group(2))
