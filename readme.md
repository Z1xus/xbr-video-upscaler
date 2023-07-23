## xbr-video-upscaler
Use [ImageResizer](https://github.com/Hawkynt/2dimagefilter) to process videos.

> ⚠️ WIP, do not expect a working program

### The name lies, you can use many different pixel art scaling algorithms:
+ XBR
+ HQX
+ LQX
+ NearestNeighbor
+ Bilinear
+ Bicubic
+ and others... (see [ImageResizer wiki](https://code.google.com/archive/p/2dimagefilter/wikis/ImageScaling.wiki))

### Usage:
1. Clone the repository
```bash
git clone https://github.com/Z1xus/xbr-video-upscaler
```
2. Install dependencies
```bash
pip install -r .\requirements.txt
```
3. Change config.ini
```ini
[upscaler]
magnification_factor = 2
algorithm = XBR

[ffmpeg]
args = -c:v libx264 -preset slow -crf 15 -aq-mode 3

[output]
container = mp4
scale_factor = 200

[imageresizer]
path = .\ImageResizer.exe

```
4. Run it 
```bash
python3 main.py [-h] -i INPUT [-v]
```
