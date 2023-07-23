import os
import sys
import argparse
import configparser
import cv2
import subprocess
import shutil
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

def signal_handler(sig, frame):
	exit_event.set()
	print('Ctrl+C received, cleaning up...')
	cleanup(temp_dir)
	sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

exit_event = threading.Event()

def cleanup(temp_directory):
	for path_file in os.scandir(temp_directory):
		os.remove(path_file.path)
	os.rmdir(temp_directory)

def check_dependencies(config):
	imageresizer_path = config['imageresizer']['path']
	ffmpeg_path = 'ffmpeg'

	if not (os.path.isfile(imageresizer_path) and os.access(imageresizer_path, os.X_OK)):
		print(f'Error: ImageResizer must be correctly installed and executable. Current path:\nImageResizer: {imageresizer_path}')
		sys.exit(1)
	if not shutil.which(ffmpeg_path):
		print(f'Error: ffmpeg must be correctly installed. Current path:\nffmpeg: {ffmpeg_path}')
		sys.exit(1)

def get_fps(video_path):
	if not os.path.isfile(video_path):
		print(f'Error: input video file not found. Given path:\n{video_path}')
		sys.exit(1)
		
	video = cv2.VideoCapture(video_path)
	fps = video.get(cv2.CAP_PROP_FPS)
	video.release()
	return fps

def get_resolution(video_path):
	video = cv2.VideoCapture(video_path)
	width = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))
	height = int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))
	video.release()
	return width, height

def extract_frames(video_path, temp_directory):
	vidcap = cv2.VideoCapture(video_path)
	success, image = vidcap.read()
	count = 0
	while success:
		frame_file = os.path.join(temp_directory, f"frame_{count:05}.png")
		success = cv2.imwrite(frame_file, image) 
		if not success or not os.path.exists(frame_file):
			print(f"Frame extraction failed for frame {count}")
			sys.exit(1)
		success, image = vidcap.read()
		count += 1
	return count

def upscale_frame(i, temp_directory, imageresizer_path, scale_factor, magnification_factor, algorithm, original_resolution, verbose):
	new_width = int(original_resolution[0] * scale_factor)
	new_height = int(original_resolution[1] * scale_factor)

	in_frame = os.path.join(temp_directory, f"frame_{i:05}.png")
	out_frame = os.path.join(temp_directory, f"frame_{i:05}_up.png")

	try:
		if scale_factor != float(magnification_factor):
			cmd = [imageresizer_path, '/load', in_frame, '/resize', 'auto', f'{algorithm} {magnification_factor}x', '/resize', f'{new_width}x{new_height}', 'Lanczos', '/save', out_frame]
		else:
			cmd = [imageresizer_path, '/load', in_frame, '/resize', 'auto', f'{algorithm} {magnification_factor}x', '/save', out_frame]

		if verbose:
			print(f"Running command: {' '.join(cmd)}")

		process_output = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		if verbose:
			print(process_output.stdout.decode('utf-8'))
			print(process_output.stderr.decode('utf-8'))

	except subprocess.CalledProcessError as e:
		print(f'Error: Upscaling frame {i} failed with exit code {e.returncode}.')
		if verbose:
			print(f"Command: {' '.join(cmd)}")
			print(f"Output: {e.output.decode('utf-8')}")
		cleanup(temp_directory)
		sys.exit(1)
	except Exception as e:
		print(f'Unexpected error occurred during upscaling frame {i}: {str(e)}')
		if verbose:
			print(f"Command: {' '.join(cmd)}")
		cleanup(temp_directory)
		sys.exit(1)

def upscale_frames(temp_directory, total_frames, imageresizer_path, scale_factor, magnification_factor, algorithm, original_resolution, verbose):
	with ThreadPoolExecutor() as executor:
		futures = [executor.submit(upscale_frame, i, temp_directory, imageresizer_path, scale_factor, magnification_factor, algorithm, original_resolution, verbose) for i in range(total_frames)]
		
		for f in tqdm(as_completed(futures), total=total_frames, desc="Upscaling frames", unit="frame"):
			pass

def get_missing_frames(total_frames, temp_directory):
	return [i for i in range(total_frames) if not os.path.exists(os.path.join(temp_directory, f'frame_{i:05}_up.png'))]

def encode_video(input_video, output_name, temp_directory, total_frames, ffmpeg_args, verbose):
	fps = get_fps(input_video)
	frame_path_list = os.path.join(temp_directory, 'frame_%05d_up.png')

	missing_frames = get_missing_frames(total_frames, temp_directory)

	if missing_frames:
		if len(missing_frames) > 10:
			print(f"Missing upscaled frames: from {missing_frames[0]} to {missing_frames[-1]}")
		else:
			print(f"Missing upscaled frames: {missing_frames}")
		cleanup(temp_directory)
		sys.exit(1)

	ffmpeg_cmd = ['ffmpeg', '-r', str(fps), '-i', frame_path_list, '-i', input_video, '-map', '0:v', '-map', '1:a']

	if ffmpeg_args:
		ffmpeg_cmd.extend(ffmpeg_args.split(' '))
	else:
		print("Falling back to the default ffmpeg arguments.")
		ffmpeg_cmd.extend(['-c:v', 'libx264', '-preset', 'medium', '-tune', 'animation', '-crf', '15', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-shortest'])

	ffmpeg_cmd.append(output_name)

	try:
		if verbose:
			print(f"Running command: {' '.join(ffmpeg_cmd)}")
			process_output = subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
			print(process_output.stdout.decode('utf-8'))
			print(process_output.stderr.decode('utf-8'))
		else:
			subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
	except subprocess.CalledProcessError as e:
		print(f'Error: Encoding video failed with exit code {e.returncode}.')
		if verbose:
			print(f"Command: {' '.join(ffmpeg_cmd)}")
			print(f"Output: {e.stderr.decode('utf-8')}")
	except Exception as e:
		print(f'Unexpected error occurred during video encoding: {str(e)}')
		if verbose:
			print(f"Command: {' '.join(ffmpeg_cmd)}")

def no_overwrite(out_filename):
	counter = 1
	filename, file_extension = os.path.splitext(out_filename)

	while os.path.exists(out_filename):
		out_filename = f"{filename}({counter}){file_extension}"
		counter += 1

	return out_filename

if __name__ == "__main__":
	parser = argparse.ArgumentParser(
	description=f"xbr-video-upscaler",
	epilog=f"by Z1xus <3\nhttps://github.com/z1xus/xbr-video-upscaler",
	formatter_class=argparse.RawDescriptionHelpFormatter,
	)
	parser.add_argument('-i', '--input', help='Input video file', required=True)
	parser.add_argument('-v', '--verbose', help='Show verbose output', action='store_true')
	args = parser.parse_args()

	config = configparser.ConfigParser()
	config.read('config.ini')

	check_dependencies(config)

	temp_dir = '.temp_frames'
	os.makedirs(temp_dir, exist_ok=True)

	print("Extracting frames...")
	total_frames = extract_frames(args.input, temp_dir)

	scale_factor = float(config['output']['scale_factor']) / 100
	magnification_factor = config['upscaler']['magnification_factor']
	algorithm = config['upscaler']['algorithm']
	original_dimensions = get_resolution(args.input)
	upscale_frames(temp_dir, total_frames, config['imageresizer']['path'], scale_factor, magnification_factor, algorithm, original_dimensions, args.verbose)

	out_filename = f"{os.path.splitext(args.input)[0]}_upscaled_{algorithm}{magnification_factor}x.{config['output']['container']}"
	out_filename = no_overwrite(out_filename)

	encode_video(args.input, out_filename, temp_dir, total_frames, config['ffmpeg']['args'], args.verbose)

	cleanup(temp_dir)
