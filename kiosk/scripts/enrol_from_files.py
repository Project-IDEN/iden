"""Stand in for the kiosk: enrol a face from image files.

    uv run --with httpx kiosk/scripts/enrol_from_files.py \
        --issuer http://localhost:8000 --client-secret <kiosk secret> \
        --ticket <ticket from the dashboard> FRAMES_DIR

The provider answers with the steps it wants — look ahead, two head movements,
four screen colours — one frame each. FRAMES_DIR must hold that many images,
sorted by name in the same order; the script prints the steps so you can name
them to match. Real liveness needs real captures: stills of one photo fail the
movement and colour checks, which is the point of them.

Until the kiosk app exists (Phase 8), this is how to exercise enrolment end to end.
"""

import argparse
import sys
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrol a face from image files.")
    parser.add_argument("frames", type=Path)
    parser.add_argument("--issuer", default="http://localhost:8000")
    parser.add_argument("--client-id", default="kiosk")
    parser.add_argument("--client-secret", required=True)
    parser.add_argument("--ticket", required=True)
    args = parser.parse_args()

    with httpx.Client(base_url=args.issuer, timeout=60) as http:
        token = http.post(
            "/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": args.client_id,
                "client_secret": args.client_secret,
                "scope": "biometric:enroll",
            },
        )
        token.raise_for_status()
        headers = {"Authorization": f"Bearer {token.json()['access_token']}"}

        challenge = http.post(
            "/biometric/enroll/challenge", headers=headers, json={"ticket": args.ticket}
        )
        if challenge.status_code != 200:
            sys.exit(f"{challenge.status_code}: {challenge.text}")
        body = challenge.json()
        print(f"Enrolling {body['displayName']}. Steps:")
        for index, step in enumerate(body["steps"]):
            print(f"  {index:2d}  {step}")

        files = sorted(
            p
            for p in args.frames.iterdir()
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
        if len(files) != len(body["steps"]):
            sys.exit(
                f"Need {len(body['steps'])} frames in {args.frames}, found {len(files)}."
            )

        response = http.post(
            "/biometric/enroll",
            headers=headers,
            data={"ticket": args.ticket, "faceChallengeId": body["faceChallengeId"]},
            files=[
                (
                    "frames",
                    (
                        p.name,
                        p.read_bytes(),
                        "image/png" if p.suffix == ".png" else "image/jpeg",
                    ),
                )
                for p in files
            ],
        )
        print(response.status_code, response.text)


if __name__ == "__main__":
    main()
