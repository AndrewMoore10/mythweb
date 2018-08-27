#!/usr/bin/perl
#
# MythWeb Streaming/Download module
#
# @url       $URL$
# @date      $Date$
# @version   $Revision$
# @author    $Author$
#

    use POSIX qw(ceil floor);

# round to the nearest even integer
    sub round_even {
        my ($in) = @_;
        my $n = floor($in);
        return ($n % 2 == 0) ? $n : ceil($in);
    }

    our $ffmpeg_pid;
    our $ffmpeg_pgid;

# Shutdown cleanup, of various types
    $ffmpeg_pgid = setpgrp(0,0);
    $SIG{'TERM'} = \&shutdown_handler;
    $SIG{'PIPE'} = \&shutdown_handler;
    END {
        shutdown_handler();
    }
    sub shutdown_handler {
        kill(1, $ffmpeg_pid) if ($ffmpeg_pid);
        kill(-1, $ffmpeg_pgid) if ($ffmpeg_pgid);
    }

# Find ffmpeg
    $ffmpeg = '';
    foreach my $path (split(/:/, $ENV{'PATH'}.':/usr/local/bin:/usr/bin'), '.') {
        if (-e "$path/mythffmpeg") {
            $ffmpeg = "$path/mythffmpeg";
            last;
        }
        if (-e "$path/ffmpeg") {
            $ffmpeg = "$path/ffmpeg";
            last;
        }
        elsif ($^O eq 'darwin' && -e "$path/ffmpeg.app") {
            $ffmpeg = "$path/ffmpeg.app";
            last;
        }
    }

# set video variables
    my $width    = 1280;
    my $vbitrate = 19390;
    my $abitrate = 128;
    my $fps = 59.94;

    if($resolution eq 'sd'){
       $width = 320;
       $vbitrate = 2048;
       $fps = 29.97;
    }

# auto-detect height based on aspect ratio
    $sh = $dbh->prepare('SELECT data FROM recordedmarkup WHERE chanid=? ' .
                        'AND starttime=FROM_UNIXTIME(?) AND type=30 ' .
                        'AND data IS NOT NULL ORDER BY mark LIMIT 1');
    $sh->execute($chanid,$starttime);
    $x = $sh->fetchrow_array;           # type = 30
    $sh->finish();

    $sh = $dbh->prepare('SELECT data FROM recordedmarkup WHERE chanid=? ' .
                        'AND starttime=FROM_UNIXTIME(?) AND type=31 ' .
                        'AND data IS NOT NULL ORDER BY mark LIMIT 1');
    $sh->execute($chanid,$starttime);
    $y = $sh->fetchrow_array if ($x);   # type = 31
    $sh->finish();

    if (!$x || !$y || $x <= 720) {      # <=720 means SD
        $sh = $dbh->prepare('SELECT recordedmarkup.type, ' .
               'recordedmarkup.data '.
               'FROM recordedmarkup ' .
               'WHERE recordedmarkup.chanid = ? ' .
               'AND recordedmarkup.starttime = FROM_UNIXTIME(?)  ' .
               'AND recordedmarkup.type IN (10, 11, 12, 13, 14) ' .
               'GROUP BY recordedmarkup.type  ' .
               'ORDER BY SUM((SELECT IFNULL(rm.mark, recordedmarkup.mark) ' .
               '   FROM recordedmarkup AS rm ' .
               '   WHERE rm.chanid = recordedmarkup.chanid ' .
               '   AND rm.starttime = recordedmarkup.starttime ' .
               '   AND rm.type IN (10, 11, 12, 13, 14)  ' .
               '   AND rm.mark > recordedmarkup.mark ' .
               '   ORDER BY rm.mark ASC LIMIT 1)- recordedmarkup.mark) DESC ' .
               'LIMIT 1');
        $sh->execute($chanid,$starttime);
        $aspect = $sh->fetchrow_hashref;
        $sh->finish();

        if( $aspect->{'type'} == 10 ) {
            $x = $y = 1;
        } elsif( $aspect->{'type'}== 11 ) {
            $x = 4; $y = 3;
        } elsif( $aspect->{'type'}== 12 ) {
            $x = 16; $y = 9;
        } elsif( $aspect->{'type'}== 13 ) {
            $x = 2.21; $y = 1;
        } elsif( $aspect->{'type'}== 14 ) {
            $x = $aspect->{'data'}; $y = 10000;
        } else {
            $x = 4; $y = 3;
        }
    }
    $height = round_even($width * ($y/$x));

    $width    = 320 unless ($width    && $width    > 1);
    $height   = 240 unless ($height   && $height   > 1);
    $vbitrate = 256 unless ($vbitrate && $vbitrate > 1);
    $abitrate = 64  unless ($abitrate && $abitrate > 1);
    $duration = ($outtime + 1) - $intime;
    $pre_ss = $intime - floor($intime *.02); # fast seek for first %90
    $post_ss = ceil($intime *.02); # accurate seek for last %10;

    my ($ffmpeg_command) = $ffmpeg
                        .' -y'
                        .' -ss '.shell_escape($pre_ss)
                        .' -i '.shell_escape($filename)
                        .' -ss '.shell_escape($post_ss)
                        .' -s '.shell_escape("${width}x${height}")
                        .' -deinterlace'
                        .' -ar 48000'
                        .' -t '.shell_escape($duration)
                        .' -b:a '.shell_escape("${abitrate}k")
                        .' -b:v '.shell_escape("${vbitrate}k")
                        .' -f mpegts'
                        .' -r 59.94'
                        .' /dev/stdout 2>/dev/null |';

    if( $format eq 'mov') {
      $ffmpeg_command = $ffmpeg
                        .' -y'
                        .' -ss '.shell_escape($pre_ss)
                        .' -i '.shell_escape($filename)
                        .' -ss '.shell_escape($post_ss)
                        .' -s '.shell_escape("${width}x${height}")
                        .' -deinterlace'
                        .' -ar 48000'
                        .' -t '.shell_escape($duration)
                        .' -b:a '.shell_escape("${abitrate}k")
                        .' -b:v '.shell_escape("${vbitrate}k")
                        .' -r '.shell_escape("${fps}")
                        .' -f mov'
                        .' -frag_duration 3600'
                        .' /dev/stdout 2>/dev/null |';
    }
    elsif( $format eq 'mp4') {
        $ffmpeg_command = $ffmpeg
                        .' -y'
                        .' -ss '.shell_escape($pre_ss)
                        .' -i '.shell_escape($filename)
                        .' -ss '.shell_escape($post_ss)
                        .' -s '.shell_escape("${width}x${height}")
                        .' -deinterlace'
                        .' -ar 48000'
                        .' -t '.shell_escape($duration)
                        .' -b:a '.shell_escape("${abitrate}k")
                        .' -b:v '.shell_escape("${vbitrate}k")
                        .' -r '.shell_escape("${fps}")
                        .' -f h264'
                        .' /dev/stdout 2>/dev/null |';
    }
    elsif( $format eq 'mpg') {
        $ffmpeg_command = $ffmpeg
                        .' -y'
                        .' -ss '.shell_escape($pre_ss)
                        .' -i '.shell_escape($filename)
                        .' -ss '.shell_escape($post_ss)
                        .' -s '.shell_escape("${width}x${height}")
                        .' -deinterlace'
                        .' -ar 48000'
                        .' -t '.shell_escape($duration)
                        .' -b:a '.shell_escape("${abitrate}k")
                        .' -b:v '.shell_escape("${vbitrate}k")
                        .' -f mpegts'
                        .' -r '.shell_escape($fps)
                        .' /dev/stdout 2>/dev/null |';
    }
    elsif( $format eq 'avi') {
        $ffmpeg_command = $ffmpeg
                        .' -y'
                        .' -ss '.shell_escape($pre_ss)
                        .' -i '.shell_escape($filename)
                        .' -ss '.shell_escape($post_ss)
                        .' -t '.shell_escape($duration)
                        .' -s '.shell_escape("${width}x${height}")
                        .' -b:a '.shell_escape("${abitrate}k")
                        .' -b:v '.shell_escape("${vbitrate}k")
                        .' -r '.shell_escape($fps)
                        .' -f avi'
                        .' /dev/stdout 2>/dev/null |';
    }

#                        .' -y'
#                        .' -i '.shell_escape($filename)
#                        .' -s 1280x720'
#                        .' -g 30'
#                        .' -r 59.94'
#                        .' -f hdv'
#                        .' -deinterlace'
#                        .' -async 2'
#                        .' -ac 2'
#                        .' -ar 11025'
#                        .' -ab 128k'
#                        .' -b 19.39m'
#                        .' /dev/stdout 2>/dev/null |';

#AM - reroute to server pre-encoded flv
    my($shortname, $path, $ext) = fileparse($filename, qr/\.[^.]*/);
    if( $format ){
        $ext = ".".$format;
    }
    my $flvfilename = $filename.".flv";
    my $cat_command = "cat ".shell_escape($filename).".flv |";

# Print the movie
    $ffmpeg_pid = open(DATA, $ffmpeg_command);

    unless ($ffmpeg_pid) {
        print header(),
                #"Can't do ffmpeg: $!\n${ffmpeg_command}";
                "Can't do cat: $!\n${cat_command}";
                1;
        exit;
    }
    # Guess the filesize based on duration and bitrate. This allows for progressive download behavior
    my $lengthSec;
    $dur = `ffmpeg -i $filename 2>&1 | grep "Duration" | cut -d ' ' -f 4 | sed s/,//`;
    if ($dur && $dur =~ /\d*:\d*:.*/) {
        @times = split(':',$dur);
        $lengthSec = $times[0]*3600+$times[1]*60+$times[2];
        $lengthSec = $duration;
        $size = int(1.05*$lengthSec*($vbitrate*1024+$abitrate*1024)/8);
        print header(-type => 'video/mpeg','Content-Length' => $size, -attachment => $shortname.'_'.$intime.'_'.$outtime.$ext);
    } else {
        print header(-type => 'video/x-flv');
    }

#    # Guess the filesize based on duration and bitrate. This allows for progressive download behavior
 #   my $lengthSec;
  #  $dur = `ffmpeg -i $filename 2>&1 | grep "Duration" | cut -d ' ' -f 4 | sed s/,//`;
  ##  if ($dur && $dur =~ /\d*:\d*:.*/ && false) {
   #     @times = split(':',$dur);
   #     $lengthSec = $times[0]*3600+$times[1]*60+$times[2];
   #     $lengthSec = $duration;
   #     $size = int(1.05*$lengthSec*($vbitrate*1024+$abitrate*1024)/8);
   #     print header(-type => 'application/octet-stream','Content-Length' => $size);
   #     print header(Content-Transfer-Encoding => 'Binary');
   #     print header(-attachment => $file_name.'_'.$intime.'_'.$outtime);
   # } else {
   #     print header(-type => 'video/flv');
   # }

    my $buffer;
    if (read DATA, $buffer, 53) {
        print $buffer;
        read DATA, $buffer, 8;
        $durPrint = reverse pack("d",$lengthSec);
        print $durPrint;
        while (read DATA, $buffer, 262144) {
            print $buffer;
        }
    }
    close DATA;

    1;
