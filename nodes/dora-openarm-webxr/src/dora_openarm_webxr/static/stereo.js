// Copyright 2026 Enactic, Inc.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// Draws the head camera as a stereo panel inside the WebXR session, with
// optional mono gripper-camera panels fixed at the lower left and right.
// Selected with "view: stereo" in the view configuration, and meant to
// be paired with "panel: lock: head" there.
//
// The panel is locked to the operator's head. The camera sits on a neck
// that follows them, so the image already lags; keeping the frame
// steady makes that lag far easier to tolerate than a whole view that
// slides late.
//
// The camera sees less than the headset shows, so the panel covers the
// field of view it is given and leaves the rest of the display empty.
// Giving it more than the camera really sees fills more of the view but
// magnifies. All of these numbers come from the node over
// `/view_configuration`.

const VERTEX_SHADER = `
attribute vec2 a_corner;
uniform mat4 u_projection;
uniform vec2 u_half_extent;
uniform vec2 u_center;
uniform float u_distance;
uniform vec2 u_uv_offset;
varying vec2 v_uv;
void main() {
  gl_Position =
    u_projection * vec4(u_center + a_corner * u_half_extent, -u_distance, 1.0);
  // Flipped because the image starts at its top row and texture
  // coordinates start at the bottom. Done here rather than with
  // UNPACK_FLIP_Y_WEBGL, which browsers honour inconsistently.
  v_uv = vec2((a_corner.x + 1.0) * 0.5, (1.0 - a_corner.y) * 0.5) +
    u_uv_offset;
}
`;

const FRAGMENT_SHADER = `
precision mediump float;
uniform sampler2D u_texture;
varying vec2 v_uv;
void main() {
  if (v_uv.x < 0.0 || v_uv.x > 1.0 || v_uv.y < 0.0 || v_uv.y > 1.0) {
    discard;
  }
  gl_FragColor = texture2D(u_texture, v_uv);
}
`;

const SIDES = ["left", "right"];
const STREAMS = ["head_left", "head_right", "wrist_left", "wrist_right"];
// Must match STREAM_PREFIX in video.py.
const STREAM_BY_PREFIX = {
  0: "head_left",
  1: "head_right",
  2: "wrist_left",
  3: "wrist_right",
};

// Used when the configuration misses the stereo-only sections.
const DEFAULT_CAMERA = { horizontal_fov: 79.4, vertical_fov: 50.1 };

function compile(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(shader));
  }
  return shader;
}

class StereoPanel {
  #gl = null;
  #program = null;
  #buffer = null;
  #attributes = {};
  #uniforms = {};
  #textures = {};
  #pending = Object.fromEntries(STREAMS.map((stream) => [stream, null]));
  #sizes = Object.fromEntries(
    STREAMS.map((stream) => [stream, { width: 0, height: 0 }]),
  );
  #configuration = null;
  #websocket = null;

  constructor(configuration) {
    this.#configuration = configuration;

    const scheme = location.protocol === "https:" ? "wss://" : "ws://";
    const websocket = new WebSocket(scheme + location.host + "/video");
    websocket.binaryType = "arraybuffer";
    websocket.addEventListener("message", (event) => {
      const message = new Uint8Array(event.data);
      const stream = STREAM_BY_PREFIX[message[0]];
      if (stream === undefined) {
        return;
      }
      const jpeg = message.subarray(1);
      createImageBitmap(new Blob([jpeg], { type: "image/jpeg" }))
        .then((bitmap) => {
          // Drop anything still waiting; it is already stale.
          if (this.#pending[stream]) {
            this.#pending[stream].close();
          }
          this.#pending[stream] = bitmap;
        })
        .catch(() => {});
    });
    this.#websocket = websocket;
  }

  // Called once the WebXR session has created its WebGL context.
  attach(gl) {
    this.#gl = gl;
    const program = gl.createProgram();
    gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX_SHADER));
    gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(program));
    }
    this.#program = program;

    this.#attributes.corner = gl.getAttribLocation(program, "a_corner");
    for (const name of [
      "u_projection",
      "u_half_extent",
      "u_center",
      "u_distance",
      "u_uv_offset",
      "u_texture",
    ]) {
      this.#uniforms[name] = gl.getUniformLocation(program, name);
    }

    this.#buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.#buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
      gl.STATIC_DRAW,
    );

    for (const stream of STREAMS) {
      const texture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, texture);
      // Not a power of two, so no mipmaps and no repeating.
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      this.#textures[stream] = texture;
    }
    // The vertical flip is done in the vertex shader instead.
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
  }

  #upload() {
    const gl = this.#gl;
    for (const stream of STREAMS) {
      const bitmap = this.#pending[stream];
      if (!bitmap) {
        continue;
      }
      gl.bindTexture(gl.TEXTURE_2D, this.#textures[stream]);
      gl.texImage2D(
        gl.TEXTURE_2D,
        0,
        gl.RGBA,
        gl.RGBA,
        gl.UNSIGNED_BYTE,
        bitmap,
      );
      this.#sizes[stream] = { width: bitmap.width, height: bitmap.height };
      bitmap.close();
      this.#pending[stream] = null;
    }
  }

  // Offsets are in source pixels to match a calibration; the shader
  // wants texture coordinates.
  #uvOffset(eye) {
    const size = this.#sizes[`head_${eye}`];
    if (eye !== "right" || size.width === 0) {
      return [0, 0];
    }
    const stereo = this.#configuration.stereo || {};
    return [
      (stereo.convergence || 0) / size.width,
      (stereo.vertical_align || 0) / size.height,
    ];
  }

  #draw(stream, halfExtent, center, distance, uvOffset = [0, 0]) {
    const gl = this.#gl;
    gl.uniform2f(this.#uniforms.u_half_extent, halfExtent[0], halfExtent[1]);
    gl.uniform2f(this.#uniforms.u_center, center[0], center[1]);
    gl.uniform1f(this.#uniforms.u_distance, distance);
    gl.uniform2f(this.#uniforms.u_uv_offset, uvOffset[0], uvOffset[1]);
    gl.bindTexture(gl.TEXTURE_2D, this.#textures[stream]);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  render(session, space, frame) {
    if (!this.#gl || !this.#configuration) {
      return;
    }
    const pose = frame.getViewerPose(space);
    if (!pose) {
      return;
    }
    const gl = this.#gl;
    const layer = session.renderState.baseLayer;

    gl.bindFramebuffer(gl.FRAMEBUFFER, layer.framebuffer);
    // Transparent so passthrough shows around the panel.
    gl.clearColor(0.0, 0.0, 0.0, 0.0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.disable(gl.DEPTH_TEST);

    this.#upload();

    const distance = this.#configuration.panel.distance;
    const camera = this.#configuration.camera || DEFAULT_CAMERA;
    const toRadians = Math.PI / 180.0;
    // The panel covers exactly the field of view it is given.
    const halfExtent = [
      distance * Math.tan((camera.horizontal_fov * toRadians) / 2.0),
      distance * Math.tan((camera.vertical_fov * toRadians) / 2.0),
    ];

    gl.useProgram(this.#program);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.#buffer);
    gl.enableVertexAttribArray(this.#attributes.corner);
    gl.vertexAttribPointer(this.#attributes.corner, 2, gl.FLOAT, false, 0, 0);
    gl.uniform1i(this.#uniforms.u_texture, 0);
    gl.activeTexture(gl.TEXTURE0);

    for (const view of pose.views) {
      // "none" only happens on a monoscopic device.
      const eye = view.eye === "right" ? "right" : "left";
      const viewport = layer.getViewport(view);
      gl.viewport(viewport.x, viewport.y, viewport.width, viewport.height);
      gl.uniformMatrix4fv(
        this.#uniforms.u_projection,
        false,
        view.projectionMatrix,
      );
      this.#draw(
        `head_${eye}`,
        halfExtent,
        [0, 0],
        distance,
        this.#uvOffset(eye),
      );

      const wrist = this.#configuration.wrist_panels || {};
      if (!wrist.enabled) {
        continue;
      }
      const wristDistance = wrist.distance || 1.0;
      const wristWidth = wrist.width || 0.38;
      const horizontalOffset = wrist.horizontal_offset || 0.36;
      const verticalOffset = wrist.vertical_offset || -0.27;
      for (const side of SIDES) {
        const stream = `wrist_${side}`;
        const size = this.#sizes[stream];
        if (size.width === 0) {
          continue;
        }
        const wristHalfExtent = [
          wristWidth / 2.0,
          ((wristWidth / 2.0) * size.height) / size.width,
        ];
        const x = side === "left" ? -horizontalOffset : horizontalOffset;
        this.#draw(
          stream,
          wristHalfExtent,
          [x, verticalOffset],
          wristDistance,
        );
      }
    }
  }

  close() {
    if (this.#websocket) {
      this.#websocket.close();
      this.#websocket = null;
    }
    for (const stream of STREAMS) {
      if (this.#pending[stream]) {
        this.#pending[stream].close();
        this.#pending[stream] = null;
      }
    }
  }
}

export function createStereoPanel(configuration) {
  return new StereoPanel(configuration);
}
