"""Generate tests/fixtures/virtualdisplaymap: a small house in xLights' export format."""
import math, os
W, H = 800, 500
out = ["# Preview Size", f"{W},{H}"]
ch = 0
def model(name, pts):
    global ch
    out.append(f"# Model: '{name}'")
    for x, y in pts:
        out.append(f"{int(x)},{int(y)},0,{ch},3,RGB,2")
        ch += 3
def line(a, b, n):
    return [(a[0] + (b[0]-a[0])*i/(n-1), a[1] + (b[1]-a[1])*i/(n-1)) for i in range(n)]
model("Roof Left", line((150, 300), (400, 460), 60))
model("Roof Right", line((400, 460), (650, 300), 60))
model("Eave", line((150, 300), (650, 300), 100))
model("Window 1", line((220,200),(300,200),15)+line((300,200),(300,120),15)+line((300,120),(220,120),15)+line((220,120),(220,200),15))
model("Window 2", line((500,200),(580,200),15)+line((580,200),(580,120),15)+line((580,120),(500,120),15)+line((500,120),(500,200),15))
model("Door", line((370,30),(370,170),25)+line((370,170),(430,170),12)+line((430,170),(430,30),25))
tree = []
for i in range(16):
    for j in range(30):
        f = j/29; x = 730 + (i-7.5)/7.5*60*(1-f); tree.append((x, 30 + 300*f))
model("Mega Tree", tree)
model("Matrix", [(40+x*6, 380+y*6) for y in range(16) for x in range(16)])
here = os.path.dirname(os.path.abspath(__file__))
open(os.path.join(here, "fixtures", "virtualdisplaymap"), "w").write("\n".join(out) + "\n")
print(ch // 3, "pixels")
