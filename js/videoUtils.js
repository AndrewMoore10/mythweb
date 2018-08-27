var player = null;
var label = null;

jQuery(document).ready(function(){
    player = document.getElementById("videoPlayer");
    label = document.getElementById("playSpeedLabel");
});

function changeVideoSpeed(direction) {

    var direction = parseInt(direction);
    if (direction != 'NaN') {
        if (direction < 0 && player.playbackRate <= 1) {
            if (player.playbackRate == 1) {
                player.pause();
                player.playbackRate = 0;
            } else if (player.playbackRate < 1) {
                player.pause();
                player.playbackRate = 0;
                player.currentTime += -10;
            }
        } else if (direction > 0 && player.paused) {
            player.play();
            player.playbackRate = direction;
        } else {
            player.playbackRate += direction;
        }
        label.innerHTML = player.playbackRate + "x";
        player.setAttribute("controls", "controls");
    }
}

function play() {
    player.play();
    if (player.playbackRate == 0) player.playbackRate = 1;
    label.innerHTML = player.playbackRate + "x";
    player.setAttribute("controls", "controls");
}

function pause() {
    player.pause();
    player.playbackRate = 1;
    label.innerHTML = player.playbackRate + "x";
    player.setAttribute("controls", "controls");
}

jQuery(document).keydown( function(event) {
    if (event.which == 39) { // handler for right arrow
        event.preventDefault()
        changeVideoSpeed(1);
    } else if (event.which == 37) { // handler for left arrow
        event.preventDefault()
        changeVideoSpeed(-1);
    } else if (event.which == 32) { // handler for space
        event.preventDefault()
        if (player.paused) {
            play();
        } else player.pause();
    } else if (event.which == 40) { // handler for down arrow
        event.preventDefault()
        player.playbackRate = 1;
        label.innerHTML = player.playbackRate + "x";
    } else if (event.which == 73) { // handler for 'I'
        event.preventDefault()
        setInTime(player);
    } else if (event.which == 79) { // handler for 'O'
        event.preventDefault()
        setOutTime(player);
    } else if (event.ctrlKey && event.keyCode == 69) { //handler for ctrl+e
        event.preventDefault();
        jQuery('#exportBG').show()
        //           exportVid('<?php echo $program->url ?>', '.mpg');
    }
    //       console.log(player.playbackRate + " hererer : "+ event.which);
});

jQuery('input[type="text"]').keydown(function(event) {
    if (event.which == 39) { // handler for right arrow
        event.stopPropagation();
        return true;
    } else if (event.which == 37) { // handler for left arrow
        event.stopPropagation();
        return true;
    }
});


function exportVid( dest, ext){
    jQuery('#exportBG').hide();
    if(!setDurationLabel()){
        alert("Invalid Duration");
        return false;
    }
    var inbox = toSeconds(document.getElementById('inTimeBox').value);
    var outbox = toSeconds(document.getElementById('outTimeBox').value);
    var format = (document.getElementById('format').value);
    var resolution = (document.getElementById('res').value);
    var destination = dest+ext+"?i="+inbox+"&o="+outbox+"&f="+format+"&r="+resolution;
//                        var player = document.getElementById('player_api');
//                        console.log(player.getTime());
//        alert(destination);
    window.open(destination);
    return true;
}
function setInTime( playerObject ){
   var curTime= 0 ;
   if( typeof playerObject == 'undefined'){ //handle for flowplayer
       playerObject = $f();
       curTime = playerObject.getTime();
   }
   else { //handle for html5 video
       curTime = playerObject.currentTime;
   }
   var box = document.getElementById('inTimeBox');
   box.value = toTimestamp(curTime);
   setDurationLabel();
   return false;
}
function setOutTime(playerObject){
   var curTime= 0 ;
   if( typeof playerObject == 'undefined'){ //handle for flowplayer
       playerObject = $f();
       curTime = playerObject.getTime();
   }
   else { //handle for html5 video
       curTime = playerObject.currentTime;
   }
   var box = document.getElementById('outTimeBox');
   box.value = toTimestamp(curTime);
   setDurationLabel();
   return false;
}
function setDurationLabel( ){
   var ret = true;
   var inTime = document.getElementById('inTimeBox').value;
   var outTime = document.getElementById('outTimeBox').value;
   var box = document.getElementById('duration');
   var dur = toSeconds(outTime) - toSeconds(inTime);
   if (dur <= 0 ){
       dur = 0;
       ret = false;
   }
   box.innerHTML = toTimestamp(dur);
   return ret;
}

function toTimestamp( totalSeconds) {
   var str = "";
   var hours = Math.floor(totalSeconds / (60* 60)); //hours
   var minutes = Math.floor( (totalSeconds - (hours*60*60)) / 60 );
   var seconds = Math.floor(totalSeconds % 60);
   str = padLeft(hours,2) + ":" + padLeft(minutes,2)  + ":" + padLeft(seconds,2);
   return str;
}

function toSeconds( timestamp) {
   var str = timestamp.split(":");
   var hours = parseInt(str[0]);
   var minutes = parseInt(str[1]);
   var seconds = parseInt(str[2]);
   totalSeconds = (seconds + 60 * (minutes + 60 * hours)) ;
   return totalSeconds;
}
function padLeft( str, n){
   str = str + "";
   var pad = "";
   for(i = 0 ; i < n ; i++){
       pad += "0";
   }

   var out = pad.substring(0, pad.length - str.length) + str + "";
   //alert (out);
   return out;
}
