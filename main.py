from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import httpx
import asyncio
import re
import os
import aiofiles
from pathlib import Path
import uuid
import time

app = FastAPI(
    title="YouTube MP3 Downloader API",
    description="Convert YouTube videos to MP3 using multiple services",
    version="1.0.0"
)

# Common headers for external requests
COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 11; F1 Prime 4G Build/RP1A.201005.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.7339.207 Mobile Safari/537.36",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "sec-ch-ua-platform": '"Android"',
    "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Android WebView";v="140"',
    "sec-ch-ua-mobile": "?1",
    "x-requested-with": "mark.via.gp",
    "sec-fetch-site": "cross-site",
    "sec-fetch-mode": "cors",
    "sec-fetch-dest": "empty",
    "accept-language": "fr-FR,fr;q=0.9,en-AS;q=0.8,en-MG;q=0.7,en-US;q=0.6,en;q=0.5",
    "priority": "u=1, i"
}

# Cache directory
CACHE_PATH = Path("/tmp/cache")
CACHE_PATH.mkdir(exist_ok=True)

class DownloadResponse(BaseModel):
    message: str
    title: Optional[str] = None
    download: Optional[str] = None
    music: Optional[str] = None
    thumbnail: Optional[str] = None
    filesize: Optional[str] = None
    duration: Optional[str] = None
    videoId: Optional[str] = None
    waited: Optional[int] = None
    bitrate: Optional[str] = None
    source: Optional[str] = None
    author: str = "Somby Ny Aina"

class ErrorResponse(BaseModel):
    message: str
    error: Optional[str] = None
    author: str = "Somby Ny Aina"

def extract_youtube_id(link: str) -> Optional[str]:
    """Extract YouTube video ID from various URL formats"""
    patterns = [
        # youtu.be/ID
        r"youtu\.be\/([a-zA-Z0-9_-]{11})",
        # youtube.com/watch?v=ID
        r"youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})",
        # youtube.com/v/ID
        r"youtube\.com\/v\/([a-zA-Z0-9_-]{11})",
        # youtube.com/embed/ID
        r"youtube\.com\/embed\/([a-zA-Z0-9_-]{11})",
        # youtube.com/shorts/ID
        r"youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})",
        # www.youtube.com/...
        r"www\.youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})",
        # m.youtube.com/...
        r"m\.youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})",
        # youtu.be/ID?param=value
        r"youtu\.be\/([a-zA-Z0-9_-]{11})(?:\?|$)",
        # youtube.com/watch?v=ID&other=params
        r"youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})&",
        # youtube.com/watch?other=param&v=ID
        r"youtube\.com\/watch\?.*v=([a-zA-Z0-9_-]{11})"
    ]

    for pattern in patterns:
        match = re.search(pattern, link)
        if match and match.group(1):
            return match.group(1)
    return None

@app.get("/ymp3", response_model=DownloadResponse, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def download_mp3_from_savenow(
    video_id: Optional[str] = Query(None, alias="id", description="YouTube video ID"),
    video_link: Optional[str] = Query(None, alias="link", description="Full YouTube URL")
):
    """
    Download YouTube video as MP3 using savenow.to service
    """
    full_link = video_link or (f"https://www.youtube.com/watch?v={video_id}" if video_id else None)
    
    if not full_link:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Missing video link or id",
                "usage": "/ymp3?link=https://youtube.com/watch?v=...",
                "author": "Somby Ny Aina"
            }
        )

    headers = {
        **COMMON_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://sombynyaina.gleeze.com/",
        "Cookie": "loader_session=3aHQXwrv3i1iplIgTl30xFnTuTnPKoWKi2CZdbFF"
    }

    try:
        async with httpx.AsyncClient() as client:
            # Start conversion
            fetch_url = f"https://p.savenow.to/ajax/download.php?format=mp3&url={httpx.URL(full_link)}"
            fetch_resp = await client.get(fetch_url, headers=headers)
            fetch_data = fetch_resp.json()

            title = fetch_data.get("title")
            info = fetch_data.get("info", {})
            progress_url = fetch_data.get("progress_url")

            if not progress_url:
                raise HTTPException(
                    status_code=500,
                    detail={
                        "message": "Failed to start conversion",
                        "response": fetch_data,
                        "author": "Somby Ny Aina"
                    }
                )

            # Poll for conversion progress
            download_url = None
            wait_count = 0
            max_attempts = 30  # ~45 seconds max wait

            while not download_url and wait_count < max_attempts:
                prog_resp = await client.get(progress_url, headers=headers)
                prog_data = prog_resp.json()

                if (prog_data.get("success") and 
                    prog_data.get("progress", 0) >= 1000 and 
                    prog_data.get("download_url")):
                    download_url = prog_data["download_url"]
                    break

                await asyncio.sleep(1.5)
                wait_count += 1

            if not download_url:
                raise HTTPException(
                    status_code=500,
                    detail={
                        "message": "Conversion timeout - please try again",
                        "author": "Somby Ny Aina"
                    }
                )

            return DownloadResponse(
                message="MP3 link ready 🎶",
                title=title or info.get("title", ""),
                thumbnail=info.get("image"),
                download=download_url,
                waited=wait_count
            )

    except httpx.HTTPError as err:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Internal error while fetching MP3",
                "error": str(err),
                "author": "Somby Ny Aina"
            }
        )

@app.get("/ytmp3", response_model=DownloadResponse, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def download_mp3_from_flvto(
    link: str = Query(..., description="YouTube video URL"),
    background_tasks: BackgroundTasks = None
):
    """
    Download YouTube video as MP3 using flvto.top service with caching
    """
    if not link:
        raise HTTPException(
            status_code=400,
            detail={
                "message": 'Missing "link" query parameter',
                "usage": "/ytmp3?link=https://youtu.be/abcd1234",
                "examples": [
                    "/ytmp3?link=https://youtu.be/ZIlALB1fQVE",
                    "/ytmp3?link=https://www.youtube.com/watch?v=ZIlALB1fQVE",
                    "/ytmp3?link=https://youtube.com/watch?v=ZIlALB1fQVE",
                    "/ytmp3?link=https://m.youtube.com/watch?v=ZIlALB1fQVE",
                    "/ytmp3?link=https://youtube.com/embed/ZIlALB1fQVE",
                    "/ytmp3?link=https://youtube.com/shorts/ZIlALB1fQVE"
                ],
                "author": "Somby Ny Aina"
            }
        )

    try:
        video_id = extract_youtube_id(link)
        if not video_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Invalid YouTube link",
                    "supported_formats": [
                        "youtu.be/ID",
                        "youtube.com/watch?v=ID", 
                        "www.youtube.com/watch?v=ID",
                        "m.youtube.com/watch?v=ID",
                        "youtube.com/embed/ID",
                        "youtube.com/shorts/ID",
                        "youtube.com/v/ID"
                    ],
                    "your_link": link
                }
            )

        # Convert using flvto.top
        headers = {
            **COMMON_HEADERS,
            "Content-Type": "application/json",
            "origin": "https://flvto.site",
            "referer": "https://flvto.site/"
        }

        async with httpx.AsyncClient() as client:
            convert_resp = await client.post(
                "https://es.flvto.top/converter",
                json={"id": video_id, "fileType": "mp3"},
                headers=headers
            )
            response_data = convert_resp.json()

        if response_data.get("status") != "ok" or not response_data.get("link"):
            raise HTTPException(
                status_code=500,
                detail={
                    "message": "Conversion failed",
                    "response": response_data,
                    "videoId": video_id
                }
            )

        download_url = response_data["link"]
        title = response_data.get("title", "Unknown Title")
        filesize = response_data.get("filesize")
        duration = response_data.get("duration")

        # Clean filename for caching
        filename = f"{re.sub(r'[^\w\d\-_.]', '_', title).replace('__', '_')[:200]}.mp3"
        file_path = CACHE_PATH / filename

        # Check cache
        if file_path.exists():
            return DownloadResponse(
                message="Served from cache ✅",
                music=f"/cache/{filename}",
                title=title,
                bitrate="mp3",
                filesize=filesize,
                duration=duration,
                videoId=video_id
            )

        # Download and cache the file
        async with httpx.AsyncClient() as client:
            audio_resp = await client.get(download_url, headers={"User-Agent": COMMON_HEADERS["User-Agent"]})
            audio_resp.raise_for_status()
            
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(audio_resp.content)

        return DownloadResponse(
            message="YouTube downloaded successfully 🎧",
            music=f"/cache/{filename}",
            title=title,
            bitrate="mp3",
            filesize=filesize,
            duration=duration,
            videoId=video_id,
            source="flvto.top"
        )

    except httpx.HTTPError as err:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Internal server error",
                "error": str(err),
                "author": "Somby Ny Aina"
            }
        )

@app.get("/cache/{filename}")
async def get_cached_file(filename: str):
    """
    Serve cached MP3 files
    """
    file_path = CACHE_PATH / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="audio/mpeg"
    )

@app.get("/")
async def root():
    return {
        "message": "YouTube MP3 Downloader API",
        "endpoints": {
            "/ymp3": "Download using savenow.to service",
            "/ytmp3": "Download using flvto.top service with caching"
        },
        "author": "Somby Ny Aina"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": time.time()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)