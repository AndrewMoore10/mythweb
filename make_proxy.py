#!/usr/bin/env python
# -*- coding: UTF-8 -*-

# 2015 Michael Stucky
#
# This script is based on Raymond Wagner's transcode wrapper stub.
# Designed to be a USERJOB of the form </path to script/transcode-h264.py %JOBID%>
#
# Modifications - Drew 7/5/2015
#
# - chanid/starttime arguments needed a couple fixes to get it working
# - added ability to cut out commercials before transcode via generate_commcutlist=True
# - added ability to implement a compression ratio
#         the compression ratio estimates the input streams encoding bitrate (all streams as a one bitrate)
#         then computes an output bitrate as a factor of this bitrate, i.e., if compressionRatio=0.75
#         then the output video will be encoded at 75% of the input video bitrate. Usually one sets
#         compressionRatio < 1, resulting in a smaller output file.
#         Note the estimated bitrate is derived from the video duration
#         and file size hence it will over estimate the true video bitrate as it does not account for the
#         encapsulation overhead of the input encoding scheme nor the bitrate of any included audio streams.
#         To enable, set estimateBitrate = True and set compressionRatio to your desired value (I use 0.7).
# - added ability to change h264 encoding preset and constant rate factor (crf) settings for HD video
# - added loads of debug statements, I've kept them in to facilitate hacking -- sorry to the purists in advance
# - added status output from ffmpeg to the myth backend giving % complete, ETA and fps encode statistics.
# - added "smart" commercial detection - if needed it is run and on completion cancels any other mythcommflag jobs
#         for the transcoded recording
# Modifications - Drew 1/25/2016
# - added fix for the markup data which is inaccurate, especially when commercials are removed
#
from MythTV import Job, Recorded, System, MythDB, findfile, MythError, MythLog, datetime

from optparse import OptionParser
from glob import glob
from shutil import copyfile
import sys
import os
import errno
import threading, time
from datetime import timedelta
import re, tempfile
import Queue # thread-safe
########## IMPORTANT #####################
#
# YOU WILL NEED TO EDIT THE SETTINGS BELOW
#
########## IMPORTANT #####################

transcoder = '/usr/bin/ffmpeg'

# flush_commskip
#       True => (Default) the script will delete all commercial skip indices from the old file
#      False => the transcode will leave the commercial skip indices from the old file "as is"
flush_commskip = True

# require_commflagged
#       True => the script will ensure mythcommflag has run on the file before encoding it
#      False => (Default) the transcode will process the video file "as is"
require_commflagged = False

# generate_commcutlist
#       True => (Default) flagged commercials are removed from the output video file
#      False => flagged commercials are NOT removed from the output video file
generate_commcutlist = True

# estimateBitrate
#       True => (Default) the bitrate of the input file is estimated via size & duration
#               ** Required True for "compressionRatio" option to work.
#      False => The bitrate of the input file is unknown
estimateBitrate = True

# compressionRatio
#      0.0 - 1.0 => Set the approximate bitrate of the output relative to the
#                   detected bitrate of the input.
#                   One can think of this as the target compression rate, i.e., the
#                   compressionRatio = (output filesize)/(input filesize)
#                   h264 video quality is approximately equal to mpeg2 video quality
#                   at a compression ratio of 0.65-0.75
#                   * Note: When enabled, this value will determine the approximate
#                     relative size of the output file and input file
#                   (output filesize) = compressionRatio * (input filesize)
compressionRatio = 0.65

# enforce a max (do not exceed) bitrate for encoded HD video
# to disable set hd_max_bitrate=0
hdvideo_max_bitrate = 500  # 0 = disable or (kBits_per_sec,kbps)
hdvideo_min_bitrate = 0     # 0 = disable or (kBits_per_sec,kbps)
vbitrate_param = '-b:v 500k'

# number of seconds of video that can be held in playing device video buffers (typically 2-5 secs)
NUM_SECS_VIDEO_BUF=3        # secs
device_bufsize = NUM_SECS_VIDEO_BUF*hdvideo_max_bitrate # (kBits_per_sec,kbps)

# enforce a target bitrate for the encoder to achieve approximately
#hdvideo_tgt_bitrate = 5000   # 0 = disable or (kBits_per_sec,kbps)
hdvideo_tgt_bitrate = 0   # 0 = disable or (kBits_per_sec,kbps)

# build_seektable
#       True => Rebuild myth seek table.
#               It allows accurate ffwd,rew / seeking on the transcoded output video
#      False => (Default) Do not rebuild the myth seek table. Not working for mythtv on h264 content.
build_seektable = False

# Making this true enables a bunch of debug information to be printed as the script runs.
debug = False

# TODO - override buffer size (kB), only use when necessary for a specific target device
# bufsize_override=0       # 0 = disable or (kBits_per_sec,kbps)
# h264 encode preset
# ultrafast,superfast, veryfast, faster, fast, medium, slow, slower, veryslow
preset_HD = 'superfast'
preset_nonHD = 'slow'
preset = 'superfast'

# h264 encode constant rate factor (used for non-HD) valid/sane values 18-28
# lower values -> higher quality, larger output files,
# higher values -> lower quality, smaller output files
crf = '21'

# if HD, copy input audio streams to the output audio streams
abitrate_param_HD='-c:a copy'

# if non-HD, encode audio to AAC with libfdk_aac at a bitrate of 128kbps
abitrate_param_nonHD = '-c:a libfdk_aac -b:a 128k'

# to convert non-HD audio to AAC using ffmpeg's aac encoder
#abitrate_param_nonHD='-strict -2'

# TODO use -crf 20 -maxrate 400k -bufsize 1835k
# effectively "target" crf 20, but if the output exceeds 400kb/s, it will degrade to something more than crf 20
# TODO detect and preserve ac3 5.1 streams typically found in HD content
# TODO detect and preserve audio streams by language
# TODO detect and preserve subtitle streams by language
# TODO is mp4 or mkv better for subtitle support in playback
#   subtitle codecs for MKV containers: copy, ass, srt, ssa
#   subtitle codecs for MP4 containers: copy, mov_text

# Languages for audio stream and subtitle selection
# eng - English
# fre - French
# ger - German
# ita - Italian
# spa - Spanish
language = 'eng'

# interval between reads from the ffmpeg status file
# also defines the interval when waiting for a mythcommflag job to finish
POLL_INTERVAL=10 # secs
# mythtv automatically launched user jobs with nice level of 17
# this will add to that level (only positive values allowed unless run as root)
# e.g., NICELEVEL=1 will run with a nice level of 18. The max nicelevel is 19.
#NICELEVEL=5
NICELEVEL=0

class CleanExit:
  pass

def runjob(jobid=None, chanid=None, starttime=None, tzoffset=None):
    global estimateBitrate
    db = MythDB()

    if jobid:
        job = Job(jobid, db=db)
        chanid = job.chanid
        utcstarttime = job.starttime
    else:
        print 'Job id not found.'
        sys.exit(1)

    if debug:
        print 'chanid "%s"' % chanid
        print 'utcstarttime "%s"' % utcstarttime

    rec = Recorded((chanid, utcstarttime), db=db);
    utcstarttime = rec.starttime;
    starttime_datetime = utcstarttime

    # reformat 'starttime' for use with mythtranscode/ffmpeg/mythcommflag
    starttime = str(utcstarttime.utcisoformat().replace(u':', '').replace(u' ', '').replace(u'T', '').replace('-', ''))
    if debug:
        print 'mythtv format starttime "%s"' % starttime
    input_filesize = rec.filesize
                #sys.exit(e.retcode)

    print 'Transcoding. ' +rec.basename + " " + rec.storagegroup

    sg = findfile('/'+rec.basename, rec.storagegroup, db=db)
    if sg is None:
        print 'Local access to recording not found.'
        sys.exit(1)

    infile = os.path.join(sg.dirname, rec.basename)
    outfile = '%s.mp4' % infile.rsplit('.',1)[0]

    framerate = 59.94

    clipped_bytes=0;

    duration_secs, e = get_duration(db, rec, transcoder, infile);
    abitrate_param = abitrate_param_HD  # preserve 5.1 audio

    if debug:
        print 'Audio bitrate parameter "%s"' % abitrate_param

    # Transcode to mp4
    #if jobid:
    #     job.update({'status':4, 'comment':'Transcoding to mp4'})

    # ffmpeg output is redirected to the temporary file tmpstatusfile and
    # a second thread continuously reads this file while
    # the transcode is in-process. see while loop below for the monitoring thread
    tf = tempfile.NamedTemporaryFile()
    tmpstatusfile = tf.name
    # tmpstatusfile = '/tmp/ffmpeg-transcode.txt'
    if debug:
        print 'Using temporary file "%s" for ffmpeg status updates.' % tmpstatusfile
    res = []
    # create a thread to perform the encode
    ipq = Queue.Queue()
    t = threading.Thread(target=wrapper, args=(encode,
                        (jobid, db, job, ipq, preset, vbitrate_param, abitrate_param,
                         infile, outfile, tmpstatusfile,), res))
    t.start()
    # wait for ffmpeg to open the file and emit its initialization information
    # before we start the monitoring process
    time.sleep(1)
    # open the temporary file having the ffmeg output text and process it to generate status updates
    hangiter=0;
    with open(tmpstatusfile) as f:
        # read all the opening ffmpeg status/analysis lines
        lines = f.readlines()
        # set initial progress to -1
        prev_progress=-1
	framenum=0
	fps=1.0
        while t.is_alive():
            # read all output since last readline() call
            lines = f.readlines()
            if len(lines) > 0:
                # every ffmpeg output status line ends with a carriage return '\r'
                # split the last read line at these locations
                lines=lines[-1].split('\r')
                hangiter=0
                if len(lines) > 1 and lines[-2].startswith('frame'):
                    # since typical reads will have the last line ending with \r the last status
                    # message is at index=[-2] start processing this line
                    # replace multiple spaces with one space
                    lines[-2] = re.sub(' +',' ',lines[-2])
                    # remove any spaces after equals signs
                    lines[-2] = re.sub('= +','=',lines[-2])
                    # split the fields at the spaces the first two fields for typical
                    # status lines will be framenum=XXXX and fps=YYYY parse the values
                    values = lines[-2].split(' ')
                    if len(values) > 1:
                        if debug:
                            print 'values %s' % values
                        prev_framenum = framenum
                        prev_fps = fps
                        try:
                            # framenum = current frame number being encoded
                            framenum = int(values[0].split('=')[1])
                            # fps = frames per second for the encoder
                            fps = float(values[1].split('=')[1])
                        except ValueError, e:
			    print 'ffmpeg status parse exception: "%s"' % e
                            framenum = prev_framenum
                            fps = prev_fps
                            pass
                    # progress = 0-100 represent percent complete for the transcode
                    progress = int((100*framenum)/(duration_secs*framerate))
                    # eta_secs = estimated number of seconds until transcoding is complete
                    eta_secs = int((float(duration_secs*framerate)-framenum)/fps)
                    # pct_realtime = how many real seconds it takes to encode 1 second of video
                    pct_realtime = float(fps/framerate)
                    if debug:
                        print 'framenum = %d fps = %.2f' % (framenum, fps)
                    if progress != prev_progress:
                        if debug:
                            print 'Progress %d%% encoding %.1f frames per second ETA %d mins' \
                                  % ( progress, fps, float(eta_secs)/60)
                        if jobid:
                            progress_str = 'Transcoding to mp4 %d%% complete ETA %d mins fps=%.1f.' \
                                  % ( progress, float(eta_secs)/60, fps)
                            job.update({'status':job.RUNNING, 'comment': progress_str})
                        prev_progress = progress
                elif len(lines) > 1:
                    if debug:
                        print 'Read pathological output %s' % lines[-2]
            else:
                if debug:
                    print 'Read no lines of ffmpeg output for %s secs. Possible hang?' % (POLL_INTERVAL*hangiter)
                hangiter = hangiter + 1
                if jobid:
                    progress_str = 'Read no lines of ffmpeg output for %s secs. Possible hang?' % (POLL_INTERVAL*hangiter)
                    job.update({'status':job.RUNNING, 'comment': progress_str})
            time.sleep(POLL_INTERVAL)
        if debug:
            print 'res = "%s"' % res

    t.join(1)
    try:
        if ipq.get_nowait() == CleanExit:
            sys.exit(0)
    except Queue.Empty:
        pass

    rec.transcoded = 1
    # rec.seek.clean()
    rec.update()

    if jobid:
        job.update({'status':job.FINISHED, 'comment':'Transcode Completed'})

def get_duration(db=None, rec=None, transcoder='/usr/bin/ffmpeg', filename=None):
    task = System(path=transcoder, db=db)
    if filename is None:
        return -1
    try:
        output = task('-i "%s"' % filename, '1>&2')
    except MythError, e:
        pass

    r = re.compile('Duration: (.*?), start')
    m = r.search(e.stderr)
    if m:
        duration = m.group(1).split(':')
        duration_secs = float((int(duration[0])*60+int(duration[1]))*60+float(duration[2]))
        duration_msecs = int(1000*duration_secs)
        if debug:
            print 'Duration %s' % m.group(1)
            print 'Duration %s' % duration
            print 'Duration in seconds "%s"' % duration_secs
            print 'Duration in milliseconds "%s"' % duration_msecs
        return duration_secs, e
    return -1, e

def encode(jobid=None, db=None, job=None,
           procqueue=None, preset='slow',
           vbitrate_param='-crf:v 18',
           abitrate_param='-c:a libfdk_aac -b:a 128k',
           infile=None, outfile=None, statusfile=None):
    #    task = System(path=transcoder, db=db)
    task = System(path='nice', db=db)
    try:
        output = task(
                      '-n %s' % NICELEVEL,
                      '%s' % transcoder,
                      '-i "%s"' % infile,
                      # parameter to overwrite output file if present without prompt
                      '-y',
                      # parameter de-interlacing filter
                      # '-filter:v yadif=0:-1:1',
		      # parameter to allow streaming content
                      '-movflags +faststart',
                      # parameter needed when hdhomerun prime mpeg2 files sometime repeat timestamps
                      # '-vsync passthrough',
                      # h264 video codec
                      # '-c:v libx264',
                      '-vb 500K',
                      '-vf scale=320:-1',
                      '-preset superfast',
                      '-strict -2',
                      # presets for h264 encode that effect encode speed/output filesize
                      # '-preset:v %s' % preset,
                      # ##########  IMPORTANT  ############
                      # ffmpeg versions after 08-18-2015 include a change to force explicit IDR frames,
                      # setting this flag helps/corrects myth seektable indexing h264-encoded files
                      # uncomment the  line below if you have a recent version of ffmpeg that supports this option
                      # '-forced-idr 1',
                      # parameters to determine video encode target bitrate
                      # parameters to determine audio encode target bitrate
                      # parameter to encode all input audio streams into the output
                      # '-map 0:a',
                      # parameters to set the first output audio stream
                      # to be an audio stream having the specified language (default=eng -> English)
                      # parameter to copy input subtitle streams into the output
                      # '-c:s copy',
                      # parameters to set the first output subtitle stream
                      # to be an english subtitle stream
                      # we can control the number of encode threads (disabled)
                      # output file parameter
                      '"%s"' % outfile,
                      # redirection of output to temporaryfile
                      '> %s 2>&1 < /dev/null' % statusfile)
    except MythError, e:
        print 'Command failed with output:\n%s' % e.stderr
        if jobid:
            job.update({'status':job.ERRORED, 'comment':'Transcoding to mp4 failed'})
        procqueue.put(CleanExit)
        sys.exit(e.retcode)

def wrapper(func, args, res):
    res.append(func(*args))

def main():
    parser = OptionParser(usage="usage: %prog [options] [jobid]")

    parser.add_option('--chanid', action='store', type='int', dest='chanid',
            help='Use chanid with both starttime and tzoffset for manual operation')
    parser.add_option('--starttime', action='store', type='string', dest='starttime',
            help='Use starttime with both chanid and tzoffset for manual operation')
    parser.add_option('--tzoffset', action='store', type='int', dest='tzoffset',
            help='Use tzoffset with both chanid and starttime for manual operation')
    parser.add_option('-v', '--verbose', action='store', type='string', dest='verbose',
            help='Verbosity level')

    opts, args = parser.parse_args()

    if opts.verbose:
        if opts.verbose == 'help':
            print MythLog.helptext
            sys.exit(0)
        MythLog._setlevel(opts.verbose)

    if len(args) == 1:
        runjob(jobid=args[0])
    elif opts.chanid and opts.starttime and opts.tzoffset is not None:
        runjob(chanid=opts.chanid, starttime=opts.starttime, tzoffset=opts.tzoffset)
    else:
        print 'Script must be provided jobid, or chanid, starttime and timezone offset.'
        sys.exit(1)

if __name__ == '__main__':
    main()
