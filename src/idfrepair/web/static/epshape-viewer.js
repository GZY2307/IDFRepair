'use strict';

/*
 * Presentation-only IDF geometry viewer for IDFRepair.
 * The scene setup follows EPShape's local-first approach and uses the vendored
 * Three.js kernel distributed with EPShape. It never calls a repair endpoint.
 * EPShape license: /static/epshape-LICENSE.txt
 */

(() => {
  const parentOrigin = window.location.origin;
  const container = document.querySelector('#canvas-container');
  const emptyState = document.querySelector('#viewer-empty');
  const fileLabel = document.querySelector('#viewer-file');
  const statusLabel = document.querySelector('#viewer-status');
  const errorCaption = document.querySelector('#error-caption');
  const fitButton = document.querySelector('#fit-model');
  const focusButton = document.querySelector('#focus-error');
  const colorModeSelect = document.querySelector('#color-mode');
  const buildingStoryOption = colorModeSelect.querySelector('option[value="buildingStory"]');
  const legendBrowser = document.querySelector('#legend-browser');
  const legendItems = document.querySelector('#legend-items');
  const legendPreviousButton = document.querySelector('#legend-scroll-previous');
  const legendNextButton = document.querySelector('#legend-scroll-next');
  const roomPanel = document.querySelector('#room-panel');
  const roomList = document.querySelector('#room-list');
  const roomSearch = document.querySelector('#room-search');
  const toggleRoomsButton = document.querySelector('#toggle-rooms');
  const closeRoomsButton = document.querySelector('#close-rooms');
  const showAllRoomsButton = document.querySelector('#show-all-rooms');
  const hideAllRoomsButton = document.querySelector('#hide-all-rooms');
  const clearIsolationButton = document.querySelector('#clear-isolation');
  const viewerActions = document.querySelector('#viewer-actions');
  const colorModeControl = document.querySelector('#color-mode-control');
  const colorModeLabel = document.querySelector('#color-mode-label');
  const roomPanelTitle = document.querySelector('#room-panel-title');
  const errorKey = document.querySelector('#error-key');
  const errorKeyLabel = document.querySelector('#error-key-label');
  const viewerHint = document.querySelector('#viewer-hint');
  const issueModeLegend = document.querySelector('#issue-mode-legend');
  const issueModeTitle = document.querySelector('#issue-mode-title');
  const issueModeScope = document.querySelector('#issue-mode-scope');
  const exitIssueModeButton = document.querySelector('#exit-issue-mode');
  const issueKeyTarget = document.querySelector('#issue-key-target b');
  const issueKeyPaired = document.querySelector('#issue-key-paired b');
  const issueKeyGroup = document.querySelector('#issue-key-group b');
  const issueKeyNeutral = document.querySelector('#issue-key-neutral b');
  const issueKeyBefore = document.querySelector('#issue-key-before b');
  const issueKeyAfter = document.querySelector('#issue-key-after b');
  const occupancyControls = document.querySelector('#occupancy-controls');
  const occupancyPlayButton = document.querySelector('#occupancy-play');
  const occupancyControlsToggle = document.querySelector('#occupancy-controls-toggle');
  const occupancyDetailsToggle = document.querySelector('#occupancy-details-toggle');
  const occupancyTimeInput = document.querySelector('#occupancy-time');
  const occupancyTimeLabel = document.querySelector('#occupancy-time-label');
  const occupancyMetricSelect = document.querySelector('#occupancy-metric');
  const occupancyScenarioLabel = document.querySelector('#occupancy-scenario');
  const occupancyTimelinePeople = document.querySelector('#occupancy-timeline-people');
  const occupancyTimelineHeating = document.querySelector('#occupancy-timeline-heating');
  const occupancyTimelineCooling = document.querySelector('#occupancy-timeline-cooling');
  const occupancyTimelineCursor = document.querySelector('#occupancy-timeline-cursor');
  const occupancyClassFilters = document.querySelector('#occupancy-class-filters');
  const occupancyClassButtons = [...document.querySelectorAll('[data-agent-class]')];
  const occupancyFlowLayer = document.querySelector('#occupancy-flow-layer');
  const occupancyFlowToggle = document.querySelector('#occupancy-flow-toggle');
  const occupancyFlowEvidence = document.querySelector('#occupancy-flow-evidence');
  const occupancyDetails = document.querySelector('#occupancy-details');
  const occupancyDetailsDragHandle = document.querySelector('#occupancy-details-drag-handle');
  const occupancyDetailsClose = document.querySelector('#occupancy-details-close');
  const occupancyDetailName = document.querySelector('#occupancy-detail-name');
  const occupancyEntranceBadge = document.querySelector('#occupancy-entrance-badge');
  const occupancyConflictBadge = document.querySelector('#occupancy-conflict-badge');
  const occupancyDetailCategory = document.querySelector('#occupancy-detail-category');
  const occupancyDetailPeople = document.querySelector('#occupancy-detail-people');
  const occupancyDetailDensity = document.querySelector('#occupancy-detail-density');
  const occupancyDetailCapacity = document.querySelector('#occupancy-detail-capacity');
  const occupancyDetailFlow = document.querySelector('#occupancy-detail-flow');
  const occupancyDetailHvac = document.querySelector('#occupancy-detail-hvac');
  const occupancyDetailPhase = document.querySelector('#occupancy-detail-phase');
  const occupancyDetailScenario = document.querySelector('#occupancy-detail-scenario');
  const occupancyDetailLoad = document.querySelector('#occupancy-detail-load');
  const roomFunctionOption = colorModeSelect.querySelector('option[value="roomFunction"]');
  const occupancyOption = colorModeSelect.querySelector('option[value="occupancy"]');
  const occupancyState = window.IDFRepairOccupancyState;

  const VIEWER_COPY = Object.freeze({
    'zh-CN': {
      title: 'IDFRepair EPShape 查看器', idfGeometry: 'IDF 几何', waiting: '等待本地 IDF',
      controls: '模型查看控件', colorMode: '模型配色方式', color: '配色',
      toggleRooms: '显示或隐藏房间', fit: '适配模型', focus: '聚焦当前错误',
      canvas: '交互式 IDF 三维模型', emptyTitle: '只读 IDF 几何',
      emptyHelp: '请在修复工作台选择一个 IDF。', noGeometryTitle: '未发现详细几何',
      noGeometryHelp: '该 IDF 仍可继续诊断和修复。', noGeometryStatus: '无 BuildingSurface:Detailed 几何',
      roomVisibility: '房间显隐', rooms: '房间', closeRooms: '关闭房间面板',
      searchRooms: '搜索房间', showAll: '全部显示', hideAll: '全部不选', clearIsolation: '退出单间',
      colorLegend: '配色图例', currentError: '当前错误', showAllColors: '显示全部配色',
      previousLegend: '向左浏览图例', nextLegend: '向右浏览图例',
      filterColor: '只显示“{label}”；再次单击可退出筛选',
      hint: '拖动旋转 · Shift+拖动平移 · 滚轮缩放 · 单击查看 · 双击隔离/退出 · R 适配',
      noMatchingRoom: '没有匹配的房间', noRoomMetadata: '该 IDF 没有房间元数据',
      isolate: '单独显示', isolated: '已单独显示', unassigned: '未分配',
      inferredLevel: '标高分组 · {height} m', levels: '{count} 个楼层',
      storyFallbackMode: 'BuildingStory（按标高分组）',
      parsing: '正在解析本地 IDF 几何…',
      unavailable: '几何预览不可用', validationIssue: '验证问题', idfObject: 'IDF 对象',
      status: '{surfaces} 个表面 · {windows} 个窗体{shades} · {rooms} 个房间 · 只读',
      shades: ' · {count} 个遮阳面', exteriorWall: '外墙', interiorSurface: '室内表面',
      roof: '屋顶 / 顶棚', floor: '地面 / 楼板', window: '窗体', door: '门', shading: '遮阳面',
      adiabatic: '绝热面', other: '其他', outdoors: '室外', ground: '地面',
      surfaceBoundary: '相邻表面', normalGray: '普通灰色',
      issueMode: '问题定位图例', exitIssueMode: '退出问题定位', issueTarget: '当前问题表面',
      issuePaired: '配对表面', issueGroup: '同组问题', issueNeutral: '其他表面',
      issueBefore: '修复前轮廓', issueAfter: '修复后轮廓',
      issueScope: '{rooms} 个房间 · {levels}', issueScopeFallback: '已按表面名称定位',
      issueStories: '{count} 个真实楼层', issueElevationGroups: '{count} 个几何标高分组',
      osmPendingTitle: 'OSM 已识别', osmPendingHelp: '等待 OpenStudio 前向翻译；完成后这里显示派生 IDF 几何。',
      osmPendingStatus: 'OSM 待转换 · 尚未生成派生 IDF',
      roomFunctionMode: 'Room Function / 房间功能', occupancyMode: 'Occupancy / 人员流量',
      occupancyPlay: '播放人员流量', occupancyPause: '暂停人员流量', occupancyMetric: '人员流量着色指标',
      occupancyDetailsShow: '显示人员详情', occupancyDetailsHide: '隐藏人员详情',
      occupancyDetailsDrag: '拖动人员详情', occupancyDetailsClose: '关闭人员详情',
      occupancyControlsMinimize: '最小化人员时间条', occupancyControlsExpand: '展开人员时间条',
      metadataConflict: '源 metadata 冲突', occupancyUnavailable: '未加载 room-aware occupancy payload',
      entranceSeed: '入口种子', flowRegion: '{entrance} 区域 · 邻接 {hops} 跳',
      flowPhase: '{minutes} 分钟受控响应（非步行时间）'
    },
    en: {
      title: 'IDFRepair EPShape Viewer', idfGeometry: 'IDF geometry', waiting: 'Waiting for a local IDF',
      controls: 'Model viewer controls', colorMode: 'Model color mode', color: 'Color',
      toggleRooms: 'Show or hide rooms', fit: 'Fit model', focus: 'Focus current error',
      canvas: 'Interactive 3D IDF model', emptyTitle: 'Read-only IDF geometry',
      emptyHelp: 'Select an IDF in the repair workbench.', noGeometryTitle: 'No detailed geometry found',
      noGeometryHelp: 'The IDF remains available for diagnosis and repair.', noGeometryStatus: 'No BuildingSurface:Detailed geometry',
      roomVisibility: 'Room visibility', rooms: 'Rooms', closeRooms: 'Close room panel',
      searchRooms: 'Search rooms', showAll: 'Show all', hideAll: 'Select none', clearIsolation: 'Clear isolation',
      colorLegend: 'Color legend', currentError: 'Current error', showAllColors: 'Show all colors',
      previousLegend: 'Browse legend left', nextLegend: 'Browse legend right',
      filterColor: 'Show only “{label}”; click again to clear the filter',
      hint: 'Drag rotate · Shift+drag pan · wheel zoom · click details · double-click isolate/exit · R fit',
      noMatchingRoom: 'No matching room', noRoomMetadata: 'No room metadata in this IDF',
      isolate: 'Isolate', isolated: 'Isolated', unassigned: 'Unassigned',
      inferredLevel: 'Elevation group · {height} m', levels: '{count} stories',
      storyFallbackMode: 'BuildingStory (elevation groups)',
      parsing: 'Parsing local IDF geometry…',
      unavailable: 'Geometry preview unavailable', validationIssue: 'Validation issue', idfObject: 'IDF object',
      status: '{surfaces} surfaces · {windows} windows{shades} · {rooms} rooms · read-only',
      shades: ' · {count} shades', exteriorWall: 'Exterior wall', interiorSurface: 'Interior surface',
      roof: 'Roof / ceiling', floor: 'Ground / floor', window: 'Window', door: 'Door', shading: 'Shading',
      adiabatic: 'Adiabatic', other: 'Other', outdoors: 'Outdoors', ground: 'Ground',
      surfaceBoundary: 'Adjacent surface', normalGray: 'OpenStudio gray',
      issueMode: 'Issue-location legend', exitIssueMode: 'Exit issue location', issueTarget: 'Current issue surface',
      issuePaired: 'Paired surface', issueGroup: 'Same issue group', issueNeutral: 'Other surfaces',
      issueBefore: 'Before-repair outline', issueAfter: 'After-repair outline',
      issueScope: '{rooms} rooms · {levels}', issueScopeFallback: 'Located by surface name',
      issueStories: '{count} model stories', issueElevationGroups: '{count} geometry elevation groups',
      osmPendingTitle: 'OSM detected', osmPendingHelp: 'Waiting for OpenStudio forward translation; derived IDF geometry will appear here.',
      osmPendingStatus: 'OSM pending · derived IDF not generated yet',
      roomFunctionMode: 'Room Function', occupancyMode: 'Occupancy', occupancyPlay: 'Play occupancy',
      occupancyPause: 'Pause occupancy', occupancyMetric: 'Occupancy color metric',
      occupancyDetailsShow: 'Show occupancy details', occupancyDetailsHide: 'Hide occupancy details',
      occupancyDetailsDrag: 'Drag occupancy details', occupancyDetailsClose: 'Close occupancy details',
      occupancyControlsMinimize: 'Minimize occupancy timeline', occupancyControlsExpand: 'Expand occupancy timeline',
      metadataConflict: 'Source metadata conflict', occupancyUnavailable: 'Room-aware occupancy payload not loaded',
      entranceSeed: 'Entrance seed', flowRegion: '{entrance} region · {hops} adjacency hops',
      flowPhase: '{minutes}-minute controlled response (not walking time)'
    }
  });

  let currentLocale = 'zh-CN';
  let pendingSourceKind = null;

  function copy(key, params = {}) {
    let value = VIEWER_COPY[currentLocale]?.[key] || VIEWER_COPY.en[key] || key;
    Object.entries(params).forEach(([name, item]) => { value = value.replaceAll(`{${name}}`, String(item)); });
    return value;
  }

  if (!container || !window.THREE) {
    window.parent.postMessage(
      {type: 'idfrepair:viewer-error', reason: 'viewer_kernel_unavailable'},
      parentOrigin
    );
    return;
  }

  const COLORS = Object.freeze({
    background: 0xf4f3ef,
    exteriorWall: 0xffe16b,
    interiorSurface: 0x444444,
    adiabatic: 0xf24b91,
    roof: 0xa82525,
    floor: 0x555555,
    window: 0x47dcff,
    door: 0x1747d4,
    shading: 0x624285,
    edge: 0x050505,
    unassigned: 0x7a817e,
    normal: 0xb8bab7,
    error: 0x8cff00
  });
  const SURFACE_COLORS = Object.freeze({
    'Exterior Wall': COLORS.exteriorWall,
    'Interior Surface': COLORS.interiorSurface,
    Adiabatic: COLORS.adiabatic,
    'Roof / Ceiling': COLORS.roof,
    'Ground / Floor': COLORS.floor,
    Window: COLORS.window,
    Door: COLORS.door,
    Shading: COLORS.shading,
    Other: COLORS.unassigned
  });
  const BOUNDARY_COLORS = Object.freeze({
    Outdoors: 0x338ac0,
    Ground: 0x765035,
    Surface: 0x805aa1,
    Adiabatic: COLORS.adiabatic,
    'Ground FCfactor': 0x5d4633,
    Other: COLORS.unassigned
  });
  const errorMaterial = new THREE.MeshPhongMaterial({
    color: COLORS.error,
    emissive: 0x244d00,
    side: THREE.DoubleSide,
    shininess: 28
  });
  const markerMaterial = new THREE.MeshBasicMaterial({
    color: COLORS.error,
    depthTest: false,
    opacity: 0.94,
    transparent: true
  });
  const issueTargetMaterial = new THREE.MeshPhongMaterial({
    color: 0x8cff00, emissive: 0x244d00, side: THREE.DoubleSide, shininess: 28
  });
  const issuePairedMaterial = new THREE.MeshPhongMaterial({
    color: 0x8d72ff, emissive: 0x21174f, side: THREE.DoubleSide, shininess: 24
  });
  const issueGroupMaterial = new THREE.MeshPhongMaterial({
    color: 0xffc15b, emissive: 0x553206, side: THREE.DoubleSide, shininess: 18
  });
  const issueNeutralMaterial = new THREE.MeshPhongMaterial({
    color: 0xb8bab7, opacity: 0.42, side: THREE.DoubleSide, transparent: true, depthWrite: true, shininess: 5
  });
  const issueTargetEdgeMaterial = new THREE.LineBasicMaterial({color: 0x244d00, opacity: 1, transparent: false});
  const issuePairedEdgeMaterial = new THREE.LineBasicMaterial({color: 0x342277, opacity: 1, transparent: false});
  const issueGroupEdgeMaterial = new THREE.LineBasicMaterial({color: 0x8b5711, opacity: 1, transparent: false});
  const issueNeutralEdgeMaterial = new THREE.LineBasicMaterial({color: 0x727b77, opacity: 0.35, transparent: true});
  const lineMaterial = new THREE.LineBasicMaterial({
    color: COLORS.edge,
    opacity: 0.82,
    transparent: true
  });
  const materialCache = new Map();

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(COLORS.background);
  scene.fog = new THREE.Fog(COLORS.background, 120, 1200);

  const camera = new THREE.PerspectiveCamera(30, 1, 0.05, 3000);
  camera.up.set(0, 0, 1);
  const renderer = new THREE.WebGLRenderer({antialias: true, alpha: false});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  container.prepend(renderer.domElement);

  const modelGroup = new THREE.Group();
  modelGroup.name = 'IDF geometry';
  scene.add(modelGroup);

  const highlightGroup = new THREE.Group();
  highlightGroup.name = 'IDF error markers';
  scene.add(highlightGroup);

  const issueOverlayGroup = new THREE.Group();
  issueOverlayGroup.name = 'IDF issue geometry overlays';
  scene.add(issueOverlayGroup);

  const occupancyFlowGroup = new THREE.Group();
  occupancyFlowGroup.name = 'Airport ABM functional route arrows';
  scene.add(occupancyFlowGroup);

  const grid = new THREE.GridHelper(120, 24, 0xaeb8b5, 0xd3d9d7);
  grid.rotation.x = Math.PI / 2;
  grid.position.z = -0.02;
  scene.add(grid);

  scene.add(new THREE.AmbientLight(0x888888, 1));
  const keyLight = new THREE.DirectionalLight(0xeeeeee, 0.6);
  keyLight.position.set(28, -34, 52);
  scene.add(keyLight);

  const orbit = {
    target: new THREE.Vector3(),
    radius: 42,
    azimuth: -0.85,
    elevation: 0.58
  };
  let drag = null;
  let modelMeshes = [];
  let objectMeshes = new Map();
  let roomMeshes = new Map();
  let roomVisibility = new Map();
  let isolatedRoom = null;
  let highlightedMeshes = [];
  let currentRoots = [];
  let currentIssueMode = null;
  let issueRoleMeshes = [];
  let currentMode = 'surfaceType';
  let activeColorLabel = null;
  let currentStats = {building: 0, fenestration: 0, shading: 0};
  let currentFileName = '';
  let currentHasExplicitStories = false;
  let hasLoadedFile = false;
  let selectionState = {kind: 'none', mesh: null, roomKey: null};
  let animationFrame = 0;
  let loadRevision = 0;
  let currentOccupancy = null;
  let occupancySpacesByRoomKey = new Map();
  let occupancyTimeIndex = 0;
  let occupancyMetric = 'density';
  let occupancyMaximum = 0;
  let occupancyPlaybackTimer = null;
  let occupancyTimeline = null;
  let occupancyDetailRoomKey = null;
  let occupancyAgentClass = 'ALL';
  let occupancyFlowVisible = true;
  let occupancyDetailsDismissed = false;
  let occupancyDetailsPosition = null;
  let occupancyDetailsDrag = null;
  let occupancyControlsMinimized = false;

  function normalizeName(value) {
    return String(value || '').trim().replace(/^['"]|['"]$/g, '').toLowerCase();
  }

  function displayName(value, fallback = 'Unassigned') {
    return String(value || '').trim().replace(/^['"]|['"]$/g, '') || fallback;
  }

  function cleanIDF(text) {
    return String(text || '')
      .split(/\r?\n/)
      .map((line) => line.split('!')[0])
      .join('\n');
  }

  function parseObjects(text) {
    return cleanIDF(text)
      .split(';')
      .map((chunk) => chunk.split(',').map((field) => field.trim()))
      .filter((fields) => fields.length > 1 && fields[0]);
  }

  function numeric(value) {
    const source = String(value ?? '').trim();
    if (!source) return null;
    const parsed = Number(source);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function inferVertexCount(fields, countIndex) {
    if (String(fields[countIndex] ?? '').trim()) return null;
    const values = fields.slice(countIndex + 1).map(numeric);
    if (values.length < 9 || values.length % 3 !== 0) return null;
    return values.every((value) => value !== null) ? values.length / 3 : null;
  }

  function findVertexLayout(fields, candidates) {
    for (const countIndex of candidates) {
      const explicit = Number.parseInt(String(fields[countIndex] ?? '').trim(), 10);
      const inferred = Number.isInteger(explicit) ? null : inferVertexCount(fields, countIndex);
      const count = Number.isInteger(explicit) ? explicit : inferred;
      if (!Number.isInteger(count) || count < 3) continue;
      const start = countIndex + 1;
      if (fields.length < start + count * 3) continue;
      const values = fields.slice(start, start + count * 3).map(numeric);
      if (values.every((value) => value !== null)) {
        return {count, start, values, countIndex, inferred: inferred !== null};
      }
    }
    return null;
  }

  function zoneTransform(zone) {
    if (!zone) return {origin: [0, 0, 0], radians: 0};
    return {
      origin: zone.origin,
      radians: THREE.MathUtils.degToRad(-(zone.rotation || 0))
    };
  }

  function readVertices(layout, transform = {origin: [0, 0, 0], radians: 0}) {
    const vertices = [];
    const cosine = Math.cos(transform.radians || 0);
    const sine = Math.sin(transform.radians || 0);
    for (let index = 0; index < layout.count; index += 1) {
      const offset = index * 3;
      const localX = layout.values[offset];
      const localY = layout.values[offset + 1];
      vertices.push([
        localX * cosine - localY * sine + transform.origin[0],
        localX * sine + localY * cosine + transform.origin[1],
        layout.values[offset + 2] + transform.origin[2]
      ]);
    }
    return vertices;
  }

  function centroidArray(vertices) {
    const result = [0, 0, 0];
    vertices.forEach((vertex) => {
      result[0] += vertex[0];
      result[1] += vertex[1];
      result[2] += vertex[2];
    });
    return result.map((value) => value / Math.max(vertices.length, 1));
  }

  function inferredStory(z) {
    const rounded = Math.round((Number(z) || 0) * 100) / 100;
    return `Inferred level · ${rounded.toFixed(2)} m`;
  }

  function closestStory(z, stories) {
    if (!stories.length) return inferredStory(z);
    return stories.reduce((closest, story) => (
      Math.abs(story.z - z) < Math.abs(closest.z - z) ? story : closest
    )).name;
  }

  function assignInferredStoryGroups(surfaces) {
    const roomElevations = new Map();
    surfaces.forEach((surface) => {
      const key = roomIdentity(surface).key;
      const minimumZ = Math.min(...surface.vertices.map((vertex) => vertex[2]));
      roomElevations.set(key, Math.min(roomElevations.get(key) ?? Infinity, minimumZ));
    });
    surfaces.forEach((surface) => {
      surface.story = inferredStory(roomElevations.get(roomIdentity(surface).key));
      surface.storyIsInferred = true;
    });
  }

  function parseIDFGeometry(text) {
    const objects = parseObjects(text);
    const zones = new Map();
    const spaces = new Map();
    const spacesByZone = new Map();
    const stories = [];
    let relativeCoordinates = true;

    for (const fields of objects) {
      const type = normalizeName(fields[0]);
      if (type === 'globalgeometryrules') {
        relativeCoordinates = normalizeName(fields[3]) !== 'world';
      } else if (type === 'zone') {
        const zone = {
          name: displayName(fields[1]),
          rotation: numeric(fields[2]) || 0,
          origin: [numeric(fields[3]) || 0, numeric(fields[4]) || 0, numeric(fields[5]) || 0]
        };
        zones.set(normalizeName(zone.name), zone);
      } else if (type === 'space') {
        const rawType = fields[6] || (numeric(fields[3]) === null ? fields[3] : '');
        const space = {
          name: displayName(fields[1]),
          zoneName: displayName(fields[2]),
          spaceType: displayName(rawType)
        };
        spaces.set(normalizeName(space.name), space);
        const zoneKey = normalizeName(space.zoneName);
        if (!spacesByZone.has(zoneKey)) spacesByZone.set(zoneKey, []);
        spacesByZone.get(zoneKey).push(space);
      } else if (type === 'buildingstory' || type === 'os:buildingstory') {
        stories.push({name: displayName(fields[1]), z: numeric(fields[2]) || 0});
      }
    }

    const surfaces = [];
    const parentSurfaces = new Map();
    const stats = {building: 0, fenestration: 0, shading: 0};

    for (const fields of objects) {
      if (normalizeName(fields[0]) !== 'buildingsurface:detailed') continue;
      const layout = findVertexLayout(fields, [11, 10, 9, 12]);
      if (!layout) continue;
      const hasSpaceField = layout.countIndex >= 11;
      let zoneName = displayName(fields[4]);
      let space = hasSpaceField ? spaces.get(normalizeName(fields[5])) : null;
      if (!space) {
        const choices = spacesByZone.get(normalizeName(zoneName)) || [];
        if (choices.length === 1) space = choices[0];
      }
      if ((!zoneName || zoneName === 'Unassigned') && space) zoneName = space.zoneName;
      const zone = zones.get(normalizeName(zoneName));
      const transform = relativeCoordinates ? zoneTransform(zone) : zoneTransform(null);
      const vertices = readVertices(layout, transform);
      const center = centroidArray(vertices);
      const surface = {
        kind: 'surface',
        name: displayName(fields[1], `Building surface ${surfaces.length + 1}`),
        objectType: displayName(fields[0]),
        surfaceType: displayName(fields[2], 'Other'),
        construction: displayName(fields[3]),
        zone: zone?.name || zoneName,
        space: space?.name || 'Unassigned',
        spaceType: space?.spaceType || 'Unassigned',
        story: closestStory(center[2], stories),
        boundary: displayName(fields[hasSpaceField ? 6 : 5]),
        vertices,
        transform
      };
      surfaces.push(surface);
      parentSurfaces.set(normalizeName(surface.name), surface);
      stats.building += 1;
    }

    for (const fields of objects) {
      const type = normalizeName(fields[0]);
      if (type === 'fenestrationsurface:detailed') {
        const layout = findVertexLayout(fields, [9, 8, 10, 11]);
        if (!layout) continue;
        const parent = parentSurfaces.get(normalizeName(fields[4]));
        const transform = relativeCoordinates && parent ? parent.transform : zoneTransform(null);
        const vertices = readVertices(layout, transform);
        surfaces.push({
          kind: 'fenestration',
          name: displayName(fields[1], `Fenestration ${surfaces.length + 1}`),
          objectType: displayName(fields[0]),
          surfaceType: displayName(fields[2], 'Window'),
          construction: displayName(fields[3]),
          zone: parent?.zone || 'Unassigned',
          space: parent?.space || 'Unassigned',
          spaceType: parent?.spaceType || 'Unassigned',
          story: parent?.story || closestStory(centroidArray(vertices)[2], stories),
          boundary: parent?.boundary || 'Surface',
          vertices,
          transform
        });
        stats.fenestration += 1;
        continue;
      }

      let layout = null;
      let parent = null;
      if (type === 'shading:building:detailed' || type === 'shading:site:detailed') {
        layout = findVertexLayout(fields, [3, 2, 4]);
      } else if (type === 'shading:zone:detailed') {
        layout = findVertexLayout(fields, [4, 3, 5]);
        parent = parentSurfaces.get(normalizeName(fields[2]));
      }
      if (!layout) continue;
      const transform = relativeCoordinates && parent ? parent.transform : zoneTransform(null);
      const vertices = readVertices(layout, transform);
      surfaces.push({
        kind: 'shading',
        name: displayName(fields[1], `Shading surface ${surfaces.length + 1}`),
        objectType: displayName(fields[0]),
        surfaceType: 'Shading',
        construction: 'Unassigned',
        zone: parent?.zone || 'Unassigned',
        space: parent?.space || 'Unassigned',
        spaceType: parent?.spaceType || 'Unassigned',
        story: parent?.story || closestStory(centroidArray(vertices)[2], stories),
        boundary: 'Shading',
        vertices,
        transform
      });
      stats.shading += 1;
    }
    if (stories.length) surfaces.forEach((surface) => { surface.storyIsInferred = false; });
    else assignInferredStoryGroups(surfaces);
    return {surfaces, stats, hasExplicitStories: stories.length > 0};
  }

  function newellNormal(vertices) {
    const normal = new THREE.Vector3();
    for (let index = 0; index < vertices.length; index += 1) {
      const current = vertices[index];
      const next = vertices[(index + 1) % vertices.length];
      normal.x += (current[1] - next[1]) * (current[2] + next[2]);
      normal.y += (current[2] - next[2]) * (current[0] + next[0]);
      normal.z += (current[0] - next[0]) * (current[1] + next[1]);
    }
    return normal.normalize();
  }

  function projectContour(vertices, normal) {
    const absolute = [Math.abs(normal.x), Math.abs(normal.y), Math.abs(normal.z)];
    const dropAxis = absolute.indexOf(Math.max(...absolute));
    return vertices.map((vertex) => {
      if (dropAxis === 0) return new THREE.Vector2(vertex[1], vertex[2]);
      if (dropAxis === 1) return new THREE.Vector2(vertex[0], vertex[2]);
      return new THREE.Vector2(vertex[0], vertex[1]);
    });
  }

  function polygonGeometry(vertices) {
    if (vertices.length < 3) return null;
    const normal = newellNormal(vertices);
    if (!Number.isFinite(normal.x) || normal.lengthSq() < 0.5) return null;
    const contour = projectContour(vertices, normal);
    let triangles = THREE.ShapeUtils.triangulateShape(contour, []);
    if (!triangles.length) {
      triangles = [];
      for (let index = 1; index < vertices.length - 1; index += 1) triangles.push([0, index, index + 1]);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices.flat(), 3));
    geometry.setIndex(triangles.flat());
    geometry.computeVertexNormals();
    geometry.computeBoundingBox();
    return {geometry, normal};
  }

  function surfaceTypeCategory(surface) {
    const type = normalizeName(surface.surfaceType);
    if (surface.kind === 'shading') return 'Shading';
    if (type.includes('window') || type.includes('glass')) return 'Window';
    if (type.includes('door')) return 'Door';
    if (type.includes('roof') || type.includes('ceiling')) return 'Roof / Ceiling';
    if (type.includes('floor')) return 'Ground / Floor';
    if (type.includes('wall')) {
      const boundary = boundaryCategory(surface.boundary);
      if (boundary === 'Outdoors') return 'Exterior Wall';
      if (boundary === 'Adiabatic') return 'Adiabatic';
      return 'Interior Surface';
    }
    return 'Other';
  }

  function boundaryCategory(value) {
    const boundary = normalizeName(value);
    if (boundary.includes('outdoor')) return 'Outdoors';
    if (boundary.includes('groundfc') || boundary.includes('ground fc')) return 'Ground FCfactor';
    if (boundary.includes('ground')) return 'Ground';
    if (boundary === 'surface' || boundary.includes('zone')) return 'Surface';
    if (boundary.includes('adiabatic')) return 'Adiabatic';
    return 'Other';
  }

  function hashColor(value) {
    const source = displayName(value);
    if (source === 'Unassigned') return COLORS.unassigned;
    let hash = 2166136261;
    for (let index = 0; index < source.length; index += 1) {
      hash ^= source.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    const color = new THREE.Color();
    color.setHSL(((hash >>> 0) % 360) / 360, 0.64, 0.46);
    return color.getHex();
  }

  function hexColor(value, fallback = COLORS.unassigned) {
    const normalized = String(value || '').replace('#', '');
    return /^[0-9a-f]{6}$/i.test(normalized) ? Number.parseInt(normalized, 16) : fallback;
  }

  function occupancySpaceForSurface(surface) {
    return occupancySpacesByRoomKey.get(roomIdentity(surface).key) || null;
  }

  function occupancyDescriptor(surface) {
    const space = occupancySpaceForSurface(surface);
    if (!space || !occupancyState) return {label: 'Unassigned', color: COLORS.unassigned};
    const color = occupancyState.colorForMetric(
      space,
      occupancyTimeIndex,
      occupancyMetric,
      occupancyMaximum,
      occupancyAgentClass
    );
    return {label: 'Occupancy intensity', color: hexColor(color)};
  }

  function colorDescriptor(surface, mode = currentMode) {
    if (mode === 'roomFunction') {
      const space = occupancySpaceForSurface(surface);
      if (!space || !occupancyState) return {label: 'Unassigned', color: COLORS.unassigned};
      return {
        label: space.category,
        color: hexColor(
          currentOccupancy?.is_v3
            ? occupancyState.FUNCTION_COLORS[space.function]
            : occupancyState.CATEGORY_COLORS[space.category]
        )
      };
    }
    if (mode === 'occupancy') return occupancyDescriptor(surface);
    if (mode === 'normal') return {label: 'Normal', color: COLORS.normal};
    if (mode === 'boundary') {
      const label = boundaryCategory(surface.boundary);
      return {label, color: BOUNDARY_COLORS[label]};
    }
    if (mode === 'construction') return {label: displayName(surface.construction), color: hashColor(surface.construction)};
    if (mode === 'thermalZone') return {label: displayName(surface.zone), color: hashColor(surface.zone)};
    if (mode === 'spaceType') return {label: displayName(surface.spaceType), color: hashColor(surface.spaceType)};
    if (mode === 'buildingStory') return {label: displayName(surface.story), color: hashColor(surface.story)};
    const label = surfaceTypeCategory(surface);
    return {label, color: SURFACE_COLORS[label]};
  }

  function materialFor(surface) {
    const descriptor = colorDescriptor(surface);
    const opacity = surface.kind === 'fenestration'
      ? (surfaceTypeCategory(surface) === 'Door' ? 0.68 : 0.56)
      : (surface.kind === 'shading' ? 0.76 : 1);
    const translucent = opacity < 1;
    const lambert = currentMode === 'surfaceType'
      && ['Exterior Wall', 'Ground / Floor'].includes(descriptor.label);
    const key = `${currentMode}:${descriptor.label}:${descriptor.color}:${surface.kind}:${opacity}:${lambert}`;
    if (!materialCache.has(key)) {
      const options = {
        color: descriptor.color,
        depthWrite: !translucent,
        opacity,
        polygonOffset: surface.kind === 'fenestration',
        polygonOffsetFactor: -2,
        polygonOffsetUnits: -4,
        side: THREE.DoubleSide,
        transparent: translucent
      };
      if (!lambert) options.shininess = surface.kind === 'fenestration' ? 34 : 10;
      const Material = lambert ? THREE.MeshLambertMaterial : THREE.MeshPhongMaterial;
      materialCache.set(key, new Material(options));
    }
    return materialCache.get(key);
  }

  function surfaceCentroid(vertices) {
    const centroid = new THREE.Vector3();
    vertices.forEach((vertex) => centroid.add(new THREE.Vector3(...vertex)));
    return centroid.divideScalar(Math.max(vertices.length, 1));
  }

  function roomIdentity(surface) {
    const name = surface.space !== 'Unassigned' ? surface.space : surface.zone;
    return {key: normalizeName(name) || 'unassigned', name: displayName(name)};
  }

  function addSurface(surface) {
    const shape = polygonGeometry(surface.vertices);
    if (!shape) return;
    surface.normal = shape.normal;
    const material = materialFor(surface);
    const mesh = new THREE.Mesh(shape.geometry, material);
    const room = roomIdentity(surface);
    mesh.name = surface.name;
    mesh.renderOrder = surface.kind === 'fenestration' ? 4 : (surface.kind === 'shading' ? 2 : 1);
    mesh.userData = {
      ...surface,
      baseMaterial: material,
      centroid: surfaceCentroid(surface.vertices),
      normal: [shape.normal.x, shape.normal.y, shape.normal.z],
      roomKey: room.key,
      roomName: room.name,
      vertexCount: surface.vertices.length
    };
    modelGroup.add(mesh);
    modelMeshes.push(mesh);

    const objectKey = normalizeName(surface.name);
    if (!objectMeshes.has(objectKey)) objectMeshes.set(objectKey, []);
    objectMeshes.get(objectKey).push(mesh);
    if (!roomMeshes.has(room.key)) roomMeshes.set(room.key, {name: room.name, meshes: []});
    roomMeshes.get(room.key).meshes.push(mesh);
    if (!roomVisibility.has(room.key)) roomVisibility.set(room.key, true);

    const edgePoints = surface.vertices.map((vertex) => new THREE.Vector3(...vertex));
    edgePoints.push(edgePoints[0].clone());
    const edge = new THREE.Line(new THREE.BufferGeometry().setFromPoints(edgePoints), lineMaterial);
    edge.renderOrder = 5;
    edge.userData.roomKey = room.key;
    mesh.userData.edge = edge;
    modelGroup.add(edge);
  }

  function sharedMaterials() {
    return new Set([
      lineMaterial, errorMaterial, markerMaterial,
      issueTargetMaterial, issuePairedMaterial, issueGroupMaterial, issueNeutralMaterial,
      issueTargetEdgeMaterial, issuePairedEdgeMaterial, issueGroupEdgeMaterial, issueNeutralEdgeMaterial,
      ...materialCache.values()
    ]);
  }

  function clearGroup(group) {
    const shared = sharedMaterials();
    const disposedGeometries = new Set();
    const disposedMaterials = new Set();
    while (group.children.length) {
      const child = group.children[0];
      group.remove(child);
      child.traverse((object) => {
        if (object.geometry && !disposedGeometries.has(object.geometry)) {
          object.geometry.dispose?.();
          disposedGeometries.add(object.geometry);
        }
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        materials.filter(Boolean).forEach((material) => {
          if (shared.has(material) || disposedMaterials.has(material)) return;
          material.map?.dispose?.();
          material.dispose?.();
          disposedMaterials.add(material);
        });
      });
    }
  }

  function updateCamera() {
    const horizontal = orbit.radius * Math.cos(orbit.elevation);
    camera.position.set(
      orbit.target.x + horizontal * Math.cos(orbit.azimuth),
      orbit.target.y + horizontal * Math.sin(orbit.azimuth),
      orbit.target.z + orbit.radius * Math.sin(orbit.elevation)
    );
    camera.lookAt(orbit.target);
  }

  function cameraBasis() {
    const horizontal = Math.cos(orbit.elevation);
    const direction = new THREE.Vector3(
      horizontal * Math.cos(orbit.azimuth),
      horizontal * Math.sin(orbit.azimuth),
      Math.sin(orbit.elevation)
    ).normalize();
    const right = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 0, 1), direction);
    if (right.lengthSq() < 1e-8) right.set(0, 1, 0);
    right.normalize();
    const up = new THREE.Vector3().crossVectors(direction, right).normalize();
    return {direction, right, up};
  }

  function fitDistanceForBounds(bounds, meshes = []) {
    const center = bounds.getCenter(new THREE.Vector3());
    const {direction, right, up} = cameraBasis();
    const verticalTangent = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2);
    const horizontalTangent = verticalTangent * Math.max(camera.aspect, 0.1);
    const points = [];
    meshes.forEach((mesh) => {
      mesh.updateWorldMatrix(true, false);
      const positions = mesh.geometry?.getAttribute?.('position');
      if (!positions) return;
      for (let index = 0; index < positions.count; index += 1) {
        points.push(new THREE.Vector3().fromBufferAttribute(positions, index).applyMatrix4(mesh.matrixWorld));
      }
    });
    if (!points.length) {
      for (const x of [bounds.min.x, bounds.max.x]) {
        for (const y of [bounds.min.y, bounds.max.y]) {
          for (const z of [bounds.min.z, bounds.max.z]) points.push(new THREE.Vector3(x, y, z));
        }
      }
    }
    let distance = 0;
    points.forEach((point) => {
      const relative = point.sub(center);
      const depthTowardCamera = relative.dot(direction);
      distance = Math.max(
        distance,
        depthTowardCamera + Math.abs(relative.dot(right)) / horizontalTangent,
        depthTowardCamera + Math.abs(relative.dot(up)) / verticalTangent
      );
    });
    return Math.max(distance * 1.06, bounds.getSize(new THREE.Vector3()).length() * 0.02, 1);
  }

  function visibleModelMeshes() {
    return modelMeshes.filter((mesh) => mesh.visible);
  }

  function updateEnvironment() {
    const meshes = visibleModelMeshes().length ? visibleModelMeshes() : modelMeshes;
    if (!meshes.length) {
      grid.visible = false;
      return;
    }
    const bounds = new THREE.Box3();
    meshes.forEach((mesh) => bounds.expandByObject(mesh));
    const size = bounds.getSize(new THREE.Vector3());
    const center = bounds.getCenter(new THREE.Vector3());
    const span = Math.max(size.x, size.y, 12);
    grid.visible = true;
    grid.scale.setScalar(Math.max(span * 1.35, 24) / 120);
    grid.position.set(center.x, center.y, bounds.min.z - Math.max(span * 0.001, 0.02));
    scene.fog.near = Math.max(orbit.radius * 3, 120);
    scene.fog.far = Math.max(orbit.radius * 12, 1200);
  }

  function fitMeshes(meshes = visibleModelMeshes()) {
    const fitTargets = meshes.filter((mesh) => mesh.visible);
    if (!fitTargets.length) {
      orbit.target.set(0, 0, 0);
      orbit.radius = 42;
      updateCamera();
      updateEnvironment();
      return;
    }
    const bounds = new THREE.Box3();
    fitTargets.forEach((mesh) => bounds.expandByObject(mesh));
    bounds.getCenter(orbit.target);
    orbit.radius = fitDistanceForBounds(bounds, fitTargets);
    camera.near = Math.max(orbit.radius / 1000, 0.02);
    camera.far = Math.max(orbit.radius * 30, 1000);
    camera.updateProjectionMatrix();
    updateCamera();
    updateEnvironment();
  }

  function markerWorldRadius(mesh) {
    mesh.geometry.computeBoundingSphere();
    const surfaceRadius = mesh.geometry.boundingSphere?.radius || 1;
    return Math.max(surfaceRadius * 0.055, 0.06);
  }

  function overlayScaleForIssueBounds(mode, meshes = []) {
    const bounds = new THREE.Box3();
    meshes.filter(Boolean).forEach((mesh) => bounds.expandByObject(mesh));
    [...mode.beforePolygons, ...mode.afterPolygons].forEach((polygon) => {
      polygon.vertices.forEach((vertex) => bounds.expandByPoint(new THREE.Vector3(...vertex)));
    });
    const size = bounds.isEmpty()
      ? new THREE.Vector3(1, 1, 1)
      : bounds.getSize(new THREE.Vector3());
    const span = Math.max(size.x, size.y, size.z, 1);
    return {
      lineWidth: Math.max(1, Math.min(4, span / 24)),
      markerRadius: Math.max(span * 0.007, 0.025),
      dashSize: Math.max(span * 0.025, 0.08),
      gapSize: Math.max(span * 0.0125, 0.04)
    };
  }

  function buildIssuePolygonOverlay(polygon, scale) {
    const points = polygon.vertices.map((vertex) => new THREE.Vector3(...vertex));
    if (points.length < 3) return;
    points.push(points[0].clone());
    const before = polygon.role === 'before';
    const color = before
      ? issuePairedMaterial.color.getHex()
      : issueTargetMaterial.color.getHex();
    const lineOptions = {
      color,
      depthTest: false,
      linewidth: scale.lineWidth,
      opacity: 0.98,
      transparent: true
    };
    const material = before
      ? new THREE.LineDashedMaterial({...lineOptions, dashSize: scale.dashSize, gapSize: scale.gapSize})
      : new THREE.LineBasicMaterial(lineOptions);
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), material);
    if (before) line.computeLineDistances();
    line.renderOrder = before ? 31 : 32;
    line.userData.overlayRole = polygon.role;
    line.userData.mesh = (objectMeshes.get(normalizeName(polygon.name)) || [])[0] || null;
    issueOverlayGroup.add(line);

    polygon.vertices.forEach((vertex) => {
      const marker = new THREE.Mesh(
        new THREE.SphereGeometry(scale.markerRadius, 10, 8),
        new THREE.MeshBasicMaterial({color, depthTest: false, opacity: 0.9, transparent: true})
      );
      marker.position.set(...vertex);
      marker.renderOrder = line.renderOrder + 1;
      marker.userData.overlayRole = polygon.role;
      marker.userData.mesh = line.userData.mesh;
      issueOverlayGroup.add(marker);
    });
  }

  function displayRoot(root, index) {
    const objectName = root.objectName || root.object_name || '';
    const fieldName = root.fieldName || root.field_name || '';
    const message = root.localized_message || root.message || root.family || copy('validationIssue');
    const identity = objectName || root.objectType || root.object_type || copy('idfObject');
    return `${index + 1}. ${identity}${fieldName ? ` · ${fieldName}` : ''} — ${message}`;
  }

  function issueMaterial(role) {
    return {
      target: issueTargetMaterial,
      paired: issuePairedMaterial,
      group: issueGroupMaterial,
      neutral: issueNeutralMaterial
    }[role] || issueNeutralMaterial;
  }

  function issueEdgeMaterial(role) {
    return {
      target: issueTargetEdgeMaterial,
      paired: issuePairedEdgeMaterial,
      group: issueGroupEdgeMaterial,
      neutral: issueNeutralEdgeMaterial
    }[role] || issueNeutralEdgeMaterial;
  }

  function issueMatchedMeshes() {
    return issueRoleMeshes
      .filter(({mesh, role}) => role !== 'neutral' && mesh.visible)
      .map(({mesh}) => mesh);
  }

  function issueFocusMeshes() {
    return issueRoleMeshes
      .filter(({mesh, role}) => (role === 'target' || role === 'paired') && mesh.visible)
      .map(({mesh}) => mesh);
  }

  function issueScopeSummary(mode, matches) {
    const rooms = new Set(matches.map((mesh) => mesh.userData.roomKey).filter(Boolean));
    const stories = new Set(matches.map((mesh) => mesh.userData.story).filter(Boolean));
    const levelCopy = copy(
      currentHasExplicitStories ? 'issueStories' : 'issueElevationGroups',
      {count: stories.size || 1}
    );
    const derived = matches.length
      ? copy('issueScope', {rooms: rooms.size || 1, levels: levelCopy})
      : copy('issueScopeFallback');
    return [mode.scopeLabel, derived].filter((value, index, values) => value && values.indexOf(value) === index).join(' · ');
  }

  function issueRoleLabel(mode, role, fallbackKey) {
    return mode.roleLabels?.[role] || copy(fallbackKey);
  }

  function clearIssueMode() {
    modelMeshes.forEach((mesh) => {
      mesh.material = mesh.userData.baseMaterial;
      if (mesh.userData.edge) mesh.userData.edge.material = lineMaterial;
    });
    clearGroup(issueOverlayGroup);
    currentIssueMode = null;
    issueRoleMeshes = [];
    issueModeLegend.hidden = true;
    errorKey.hidden = false;
    legendBrowser.hidden = false;
    colorModeControl.hidden = false;
    applyVisibility();
  }

  function applyIssueMode(input = {}) {
    const stateApi = window.IDFRepairViewerIssueState;
    if (!stateApi) return [];
    clearGroup(issueOverlayGroup);
    const mode = stateApi.normalizeIssueMode(input);
    if (!mode.targetNames.length && !mode.pairedNames.length && !mode.groupNames.length
        && !mode.beforePolygons.length && !mode.afterPolygons.length) {
      clearIssueMode();
      return [];
    }
    highlightedMeshes.forEach((mesh) => { mesh.material = mesh.userData.baseMaterial; });
    highlightedMeshes = [];
    clearGroup(highlightGroup);
    errorCaption.hidden = true;
    errorCaption.textContent = '';
    currentIssueMode = mode;
    issueRoleMeshes = modelMeshes.map((mesh) => {
      const role = window.IDFRepairViewerIssueState.roleForSurface(mesh.userData.name || mesh.name, mode);
      mesh.material = issueMaterial(role);
      if (mesh.userData.edge) mesh.userData.edge.material = issueEdgeMaterial(role);
      return {mesh, role};
    });
    const focusMeshes = issueFocusMeshes();
    const overlayScale = overlayScaleForIssueBounds(mode, focusMeshes);
    mode.beforePolygons.forEach((polygon) => buildIssuePolygonOverlay(polygon, overlayScale));
    mode.afterPolygons.forEach((polygon) => buildIssuePolygonOverlay(polygon, overlayScale));
    applyVisibility();
    const matches = issueMatchedMeshes();
    issueModeTitle.textContent = mode.title || copy('issueMode');
    issueModeScope.textContent = issueScopeSummary(mode, matches);
    issueKeyTarget.textContent = issueRoleLabel(mode, 'target', 'issueTarget');
    issueKeyPaired.textContent = issueRoleLabel(mode, 'paired', 'issuePaired');
    issueKeyGroup.textContent = issueRoleLabel(mode, 'group', 'issueGroup');
    issueKeyNeutral.textContent = issueRoleLabel(mode, 'neutral', 'issueNeutral');
    issueKeyBefore.textContent = issueRoleLabel(mode, 'before', 'issueBefore');
    issueKeyAfter.textContent = issueRoleLabel(mode, 'after', 'issueAfter');
    issueModeLegend.hidden = false;
    errorKey.hidden = true;
    legendBrowser.hidden = true;
    colorModeControl.hidden = true;
    return matches;
  }

  function applyHighlights(roots = []) {
    if (currentIssueMode) clearIssueMode();
    highlightedMeshes.forEach((mesh) => { mesh.material = mesh.userData.baseMaterial; });
    highlightedMeshes = [];
    clearGroup(highlightGroup);
    currentRoots = Array.isArray(roots) ? roots : [];

    currentRoots.forEach((root, index) => {
      const objectName = root.objectName || root.object_name || '';
      const matches = objectMeshes.get(normalizeName(objectName)) || [];
      matches.forEach((mesh) => {
        mesh.material = errorMaterial;
        if (!highlightedMeshes.includes(mesh)) highlightedMeshes.push(mesh);
      });
      const anchor = matches[0]?.userData.centroid;
      if (anchor) {
        const marker = new THREE.Mesh(
          new THREE.SphereGeometry(markerWorldRadius(matches[0]), 16, 12),
          markerMaterial
        );
        marker.position.copy(anchor);
        marker.renderOrder = 20;
        marker.userData.roomKey = matches[0].userData.roomKey;
        marker.userData.mesh = matches[0];
        highlightGroup.add(marker);
      }
    });

    if (currentRoots.length) {
      errorCaption.textContent = currentRoots.slice(0, 3).map(displayRoot).join('\n');
      errorCaption.hidden = false;
    } else {
      errorCaption.hidden = true;
      errorCaption.textContent = '';
    }
    applyVisibility();
  }

  function cssColor(color) {
    return `#${new THREE.Color(color).getHexString()}`;
  }

  function localizedValue(value) {
    if (value === 'Unassigned') return copy('unassigned');
    if (String(value || '').startsWith('Inferred level · ')) {
      return copy('inferredLevel', {height: String(value).slice('Inferred level · '.length).replace(/\s*m$/, '')});
    }
    return value;
  }

  function descriptorDisplayLabel(label) {
    const roomFunctions = {
      terminal_hall: currentLocale === 'zh-CN' ? '航站楼大厅' : 'Terminal hall',
      office: currentLocale === 'zh-CN' ? '办公室' : 'Office',
      commerce_retail: currentLocale === 'zh-CN' ? '商业零售' : 'Commerce / retail',
      dining: currentLocale === 'zh-CN' ? '餐饮' : 'Dining',
      restroom: currentLocale === 'zh-CN' ? '卫生间' : 'Restroom',
      breakroom: currentLocale === 'zh-CN' ? '休息室' : 'Breakroom',
      departure_entry: currentLocale === 'zh-CN' ? '国内出发入口' : 'Domestic departure entry',
      arrival_exit: currentLocale === 'zh-CN' ? '国内到达出口' : 'Domestic arrival exit',
      baggage_claim: currentLocale === 'zh-CN' ? '国内行李提取' : 'Domestic baggage claim',
      central_hall: currentLocale === 'zh-CN' ? '中央大厅' : 'Central hall',
      concourse: currentLocale === 'zh-CN' ? '公共指廊' : 'Public concourse',
      domestic_waiting: currentLocale === 'zh-CN' ? '国内候机区' : 'Domestic waiting',
      international_arrival: currentLocale === 'zh-CN' ? '国际到达区' : 'International arrival',
      international_hall: currentLocale === 'zh-CN' ? '国际混流区' : 'International hall',
      transfer: currentLocale === 'zh-CN' ? '换层边界' : 'Vertical-transfer boundary',
      commercial: currentLocale === 'zh-CN' ? '商业' : 'Commercial',
      restaurant: currentLocale === 'zh-CN' ? '餐厅' : 'Restaurant',
      info: currentLocale === 'zh-CN' ? '信息用房' : 'Information room'
    };
    if (roomFunctions[label]) return roomFunctions[label];
    const keys = {
      'Exterior Wall': 'exteriorWall', 'Interior Surface': 'interiorSurface', Adiabatic: 'adiabatic',
      'Roof / Ceiling': 'roof', 'Ground / Floor': 'floor', Window: 'window', Door: 'door',
      Shading: 'shading', Other: 'other', Outdoors: 'outdoors', Ground: 'ground',
      Surface: 'surfaceBoundary', Normal: 'normalGray'
    };
    if (label === 'Ground FCfactor') return currentLocale === 'zh-CN' ? '地面 FCfactor' : label;
    return keys[label] ? copy(keys[label]) : localizedValue(label);
  }

  function syncLegendNavigation() {
    const maximumScroll = Math.max(0, legendItems.scrollWidth - legendItems.clientWidth);
    legendPreviousButton.disabled = legendItems.scrollLeft <= 2;
    legendNextButton.disabled = legendItems.scrollLeft >= maximumScroll - 2;
  }

  function refreshLegendNavigation() {
    legendPreviousButton.hidden = true;
    legendNextButton.hidden = true;
    const overflowed = legendItems.scrollWidth - legendItems.clientWidth > 2;
    legendBrowser.classList.toggle('is-scrollable', overflowed);
    legendPreviousButton.hidden = !overflowed;
    legendNextButton.hidden = !overflowed;
    window.requestAnimationFrame(syncLegendNavigation);
  }

  function scrollLegend(direction) {
    legendItems.scrollBy({
      left: direction * Math.max(180, legendItems.clientWidth * 0.72),
      behavior: 'smooth'
    });
  }

  function updateLegend() {
    legendItems.replaceChildren();
    if (!modelMeshes.length) {
      refreshLegendNavigation();
      return;
    }
    let entries = [];
    if (currentMode === 'occupancy' && currentOccupancy) {
      const gradient = document.createElement('span');
      gradient.className = 'occupancy-gradient';
      const minimum = document.createElement('b');
      minimum.textContent = '0';
      const swatch = document.createElement('i');
      const maximum = document.createElement('b');
      const unit = occupancyMetric === 'count'
        ? 'people'
        : (occupancyMetric === 'capacity' ? '%' : 'people/m²');
      maximum.textContent = `${occupancyMaximum.toFixed(occupancyMetric === 'density' ? 3 : 1)} ${unit}`;
      gradient.append(minimum, swatch, maximum);
      const overload = document.createElement('b');
      overload.textContent = '源容量 >100%：红色';
      gradient.append(overload);
      legendItems.append(gradient);
      refreshLegendNavigation();
      return;
    }
    if (currentMode === 'roomFunction' && currentOccupancy && occupancyState) {
      const categories = currentOccupancy.is_v3
        ? currentOccupancy.functions
        : occupancyState.CATEGORIES;
      const categoryCounts = currentOccupancy.is_v3
        ? Object.values(currentOccupancy.spaces).reduce((counts, space) => {
          counts[space.function] = (counts[space.function] || 0) + 1;
          return counts;
        }, {})
        : currentOccupancy.category_counts;
      entries = categories
        .filter((category) => Number(categoryCounts?.[category] || 0) > 0)
        .map((category) => ({
          label: category,
          color: hexColor(currentOccupancy.is_v3
            ? occupancyState.FUNCTION_COLORS[category]
            : occupancyState.CATEGORY_COLORS[category]),
          count: Number(categoryCounts[category])
        }));
    } else if (currentMode === 'normal') {
      entries = [{label: 'Normal', color: COLORS.normal, count: modelMeshes.length}];
    } else {
      const counts = new Map();
      modelMeshes.forEach((mesh) => {
        const descriptor = colorDescriptor(mesh.userData);
        const current = counts.get(descriptor.label) || {...descriptor, count: 0};
        current.count += 1;
        counts.set(descriptor.label, current);
      });
      entries = [...counts.values()].sort((a, b) => b.count - a.count);
    }
    if (activeColorLabel) entries = entries.filter((entry) => entry.label === activeColorLabel);
    if (activeColorLabel) {
      const clear = document.createElement('button');
      clear.type = 'button';
      clear.className = 'legend-clear';
      clear.textContent = copy('showAllColors');
      clear.title = copy('showAllColors');
      clear.addEventListener('click', showAllColors);
      legendItems.append(clear);
    }
    entries.forEach((entry) => {
      const interactive = currentMode !== 'normal';
      const item = document.createElement(interactive ? 'button' : 'span');
      const swatch = document.createElement('i');
      swatch.style.background = cssColor(entry.color);
      const label = descriptorDisplayLabel(entry.label);
      const text = document.createElement('span');
      text.className = 'legend-label';
      text.textContent = `${label}${entry.count ? ` (${entry.count})` : ''}`;
      item.append(swatch, text);
      if (interactive) {
        item.type = 'button';
        item.className = 'legend-filter';
        item.setAttribute('aria-pressed', String(activeColorLabel === entry.label));
        item.setAttribute('aria-label', copy('filterColor', {label}));
        item.title = `${copy('filterColor', {label})} · ${cssColor(entry.color)}`;
        item.addEventListener('click', () => toggleColorFilter(entry.label));
      } else {
        item.title = label;
      }
      legendItems.append(item);
    });
    legendItems.scrollLeft = 0;
    window.requestAnimationFrame(refreshLegendNavigation);
  }

  function toggleColorFilter(label) {
    activeColorLabel = activeColorLabel === label ? null : label;
    applyVisibility();
    updateLegend();
    fitMeshes();
  }

  function showAllColors() {
    activeColorLabel = null;
    applyVisibility();
    updateLegend();
    fitMeshes();
  }

  function updateColorMode(mode) {
    const requested = mode || 'surfaceType';
    currentMode = ['roomFunction', 'occupancy'].includes(requested) && !currentOccupancy
      ? 'surfaceType'
      : requested;
    colorModeSelect.value = currentMode;
    occupancyMaximum = currentOccupancy && occupancyState
      ? occupancyState.maximumMetric(
        currentOccupancy,
        occupancyTimeIndex,
        occupancyMetric,
        occupancyAgentClass
      )
      : 0;
    activeColorLabel = null;
    modelMeshes.forEach((mesh) => {
      const material = materialFor(mesh.userData);
      mesh.userData.baseMaterial = material;
      if (!highlightedMeshes.includes(mesh) && !currentIssueMode) mesh.material = material;
    });
    if (currentIssueMode) applyIssueMode(currentIssueMode);
    applyVisibility();
    updateLegend();
  }

  function stopOccupancyPlayback() {
    if (occupancyPlaybackTimer !== null) window.clearInterval(occupancyPlaybackTimer);
    occupancyPlaybackTimer = null;
    occupancyPlayButton.textContent = '▶';
    occupancyPlayButton.setAttribute('aria-pressed', 'false');
    occupancyPlayButton.setAttribute('aria-label', copy('occupancyPlay'));
  }

  function timelinePoints(values, scaleMaximum = null) {
    const maximum = scaleMaximum === null ? Math.max(0, ...values) : scaleMaximum;
    return values.map((value, index) => {
      const x = index * 960 / Math.max(values.length - 1, 1);
      const y = 142 - (maximum > 0 ? value / maximum : 0) * 130;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(' ');
  }

  function occupancyRoomAnchor(spaceName) {
    const room = roomMeshes.get(normalizeName(spaceName));
    if (!room?.meshes?.length) return null;
    const bounds = new THREE.Box3();
    room.meshes.forEach((mesh) => bounds.expandByObject(mesh));
    if (bounds.isEmpty()) return null;
    const center = bounds.getCenter(new THREE.Vector3());
    center.z = bounds.max.z + 2.0;
    return center;
  }

  function addOffModelBoundaryMarker(origin, flow, weight) {
    const geometry = new THREE.OctahedronGeometry(0.65 + weight * 0.9, 0);
    const material = new THREE.MeshBasicMaterial({
      color: flow.boundary_direction === 'incoming' ? 0x237f70 : 0x8a4fb5,
      depthTest: false,
      opacity: 0.72 + weight * 0.24,
      transparent: true
    });
    const marker = new THREE.Mesh(geometry, material);
    marker.position.copy(origin);
    marker.position.z += 1.0;
    marker.renderOrder = 21;
    marker.userData = {
      fromSpaceName: flow.from_space_name,
      toSpaceName: flow.to_space_name,
      toNode: flow.to_node,
      agentsPer15Minutes: flow.count,
      evidenceLayer: flow.evidence_layer,
      evidenceReference: flow.evidence_ref,
      offModelBoundary: true,
      boundaryDirection: flow.boundary_direction,
      measuredTrajectory: false
    };
    occupancyFlowGroup.add(marker);
  }

  function renderOccupancyFlowArrows() {
    clearGroup(occupancyFlowGroup);
    occupancyFlowLayer.dataset.arrowCount = '0';
    if (!currentOccupancy?.is_v3 || !occupancyState || !occupancyFlowVisible) return;
    const flows = [...occupancyState.edgeFlowSnapshot(
      currentOccupancy,
      occupancyTimeIndex,
      occupancyAgentClass
    )].sort((left, right) => right.count - left.count);
    occupancyFlowLayer.dataset.flowCount = String(flows.length);
    let missingAnchorCount = 0;
    let shortArrowCount = 0;
    let boundaryCount = 0;
    let explicitDoorCount = 0;
    let abstractEdgeCount = 0;
    const maximum = Math.max(0, ...flows.map((flow) => flow.count));
    flows.forEach((flow) => {
      const origin = occupancyRoomAnchor(flow.from_space_name || flow.to_space_name);
      const weight = maximum > 0 ? flow.count / maximum : 0;
      if (!origin) {
        missingAnchorCount += 1;
        return;
      }
      if (flow.off_model_boundary) {
        addOffModelBoundaryMarker(origin, flow, weight);
        boundaryCount += 1;
        return;
      }
      const target = occupancyRoomAnchor(flow.to_space_name);
      if (!target) {
        missingAnchorCount += 1;
        return;
      }
      const direction = target.clone().sub(origin);
      const length = direction.length();
      if (length < 0.5) {
        shortArrowCount += 1;
        return;
      }
      const isAbstraction = flow.abstraction_flag === true;
      const arrow = new THREE.ArrowHelper(
        direction.normalize(),
        origin,
        length,
        isAbstraction ? 0xd68b00 : 0x237f70,
        Math.max(0.8, Math.min(length * 0.22, 1.2 + weight * 2.8)),
        0.35 + weight * 1.2
      );
      if (isAbstraction) {
        arrow.line.material.dispose();
        arrow.line.material = new THREE.LineDashedMaterial({
          color: 0xd68b00,
          dashSize: 1.2,
          gapSize: 0.8,
          opacity: 0.42 + weight * 0.5,
          transparent: true,
          depthTest: false
        });
        arrow.line.computeLineDistances();
        abstractEdgeCount += 1;
      } else {
        explicitDoorCount += 1;
      }
      arrow.line.material.transparent = true;
      arrow.line.material.opacity = 0.42 + weight * 0.5;
      arrow.line.material.linewidth = 1 + weight * 6;
      arrow.line.material.depthTest = false;
      arrow.line.renderOrder = 20;
      arrow.cone.material.transparent = true;
      arrow.cone.material.opacity = 0.55 + weight * 0.4;
      arrow.cone.material.depthTest = false;
      arrow.cone.renderOrder = 20;
      arrow.userData = {
        fromSpaceName: flow.from_space_name,
        toSpaceName: flow.to_space_name,
        fromFunction: flow.from_function,
        toFunction: flow.to_function,
        agentsPer15Minutes: flow.count,
        evidenceLayer: flow.evidence_layer,
        evidenceLabel: flow.evidence_label,
        evidenceReference: flow.evidence_ref,
        doorInstances: flow.door_instances,
        abstractionFlag: flow.abstraction_flag,
        semanticProcessFlow: true,
        measuredTrajectory: false
      };
      occupancyFlowGroup.add(arrow);
    });
    occupancyFlowLayer.dataset.arrowCount = String(occupancyFlowGroup.children.length);
    occupancyFlowLayer.dataset.missingAnchorCount = String(missingAnchorCount);
    occupancyFlowLayer.dataset.shortArrowCount = String(shortArrowCount);
    occupancyFlowLayer.dataset.boundaryCount = String(boundaryCount);
    occupancyFlowLayer.dataset.explicitDoorCount = String(explicitDoorCount);
    occupancyFlowLayer.dataset.abstractEdgeCount = String(abstractEdgeCount);
  }

  function renderOccupancyTimeline() {
    if (!currentOccupancy || !occupancyState) {
      occupancyTimelinePeople.setAttribute('points', '');
      occupancyTimelineHeating.setAttribute('points', '');
      occupancyTimelineCooling.setAttribute('points', '');
      return;
    }
    occupancyTimeline = occupancyState.timelineTotals(currentOccupancy, occupancyAgentClass);
    occupancyTimelinePeople.setAttribute('points', timelinePoints(occupancyTimeline.occupancy));
    if (!occupancyTimeline.load_data_available) {
      occupancyTimelineHeating.setAttribute('points', '');
      occupancyTimelineCooling.setAttribute('points', '');
      return;
    }
    const thermalMaximum = Math.max(
      0,
      ...occupancyTimeline.heating_kw,
      ...occupancyTimeline.cooling_kw
    );
    occupancyTimelineHeating.setAttribute(
      'points', timelinePoints(occupancyTimeline.heating_kw, thermalMaximum)
    );
    occupancyTimelineCooling.setAttribute(
      'points', timelinePoints(occupancyTimeline.cooling_kw, thermalMaximum)
    );
  }

  function updateOccupancyDetailsToggle() {
    const visible = Boolean(currentOccupancy) && !occupancyDetailsDismissed;
    occupancyDetailsToggle.setAttribute('aria-pressed', String(visible));
    occupancyDetailsToggle.setAttribute(
      'aria-label', copy(visible ? 'occupancyDetailsHide' : 'occupancyDetailsShow')
    );
    occupancyDetailsToggle.title = occupancyDetailsToggle.getAttribute('aria-label');
  }

  function clampOccupancyDetailsPosition() {
    if (!occupancyDetailsPosition || occupancyDetails.hidden) return;
    const containerBounds = container.getBoundingClientRect();
    const detailsBounds = occupancyDetails.getBoundingClientRect();
    const controlsBounds = occupancyControls.hidden
      ? null : occupancyControls.getBoundingClientRect();
    const minimum = 8;
    const maximumX = Math.max(minimum, containerBounds.width - detailsBounds.width - minimum);
    const controlsTop = controlsBounds
      ? controlsBounds.top - containerBounds.top
      : containerBounds.height;
    const maximumY = Math.max(minimum, controlsTop - detailsBounds.height - minimum);
    occupancyDetailsPosition = {
      x: Math.max(minimum, Math.min(maximumX, occupancyDetailsPosition.x)),
      y: Math.max(minimum, Math.min(maximumY, occupancyDetailsPosition.y))
    };
    occupancyDetails.style.left = `${occupancyDetailsPosition.x}px`;
    occupancyDetails.style.top = `${occupancyDetailsPosition.y}px`;
    occupancyDetails.style.right = 'auto';
  }

  function resetOccupancyDetailsPosition() {
    occupancyDetailsPosition = null;
    occupancyDetails.style.left = '';
    occupancyDetails.style.top = '';
    occupancyDetails.style.right = '';
  }

  function setOccupancyDetailsDismissed(dismissed) {
    occupancyDetailsDismissed = Boolean(dismissed);
    updateOccupancyDetailsToggle();
    if (occupancyDetailsDismissed || !currentOccupancy) {
      occupancyDetails.hidden = true;
      return;
    }
    renderOccupancyDetails(occupancyDetailRoomKey);
  }

  function setOccupancyControlsMinimized(minimized) {
    occupancyControlsMinimized = Boolean(minimized);
    occupancyControls.classList.toggle('minimized', occupancyControlsMinimized);
    occupancyControlsToggle.setAttribute('aria-expanded', String(!occupancyControlsMinimized));
    occupancyControlsToggle.textContent = occupancyControlsMinimized ? '▴' : '▾';
    const label = copy(
      occupancyControlsMinimized ? 'occupancyControlsExpand' : 'occupancyControlsMinimize'
    );
    occupancyControlsToggle.setAttribute('aria-label', label);
    occupancyControlsToggle.title = label;
    window.requestAnimationFrame(clampOccupancyDetailsPosition);
  }

  function beginOccupancyDetailsDrag(event) {
    if (occupancyDetails.hidden || event.button !== 0) return;
    const containerBounds = container.getBoundingClientRect();
    const detailsBounds = occupancyDetails.getBoundingClientRect();
    occupancyDetailsPosition = {
      x: detailsBounds.left - containerBounds.left,
      y: detailsBounds.top - containerBounds.top
    };
    occupancyDetailsDrag = {
      pointerId: event.pointerId,
      offsetX: event.clientX - detailsBounds.left,
      offsetY: event.clientY - detailsBounds.top
    };
    occupancyDetailsDragHandle.setPointerCapture?.(event.pointerId);
    event.preventDefault();
    event.stopPropagation();
  }

  function moveOccupancyDetails(event) {
    if (!occupancyDetailsDrag || event.pointerId !== occupancyDetailsDrag.pointerId) return;
    const containerBounds = container.getBoundingClientRect();
    occupancyDetailsPosition = {
      x: event.clientX - containerBounds.left - occupancyDetailsDrag.offsetX,
      y: event.clientY - containerBounds.top - occupancyDetailsDrag.offsetY
    };
    clampOccupancyDetailsPosition();
    event.preventDefault();
    event.stopPropagation();
  }

  function endOccupancyDetailsDrag(event) {
    if (!occupancyDetailsDrag || event.pointerId !== occupancyDetailsDrag.pointerId) return;
    occupancyDetailsDragHandle.releasePointerCapture?.(event.pointerId);
    occupancyDetailsDrag = null;
    event.preventDefault();
    event.stopPropagation();
  }

  function renderOccupancyDetails(roomKey = occupancyDetailRoomKey) {
    occupancyDetailRoomKey = roomKey;
    const entry = occupancySpacesByRoomKey.get(roomKey);
    if (!currentOccupancy || !occupancyState) {
      occupancyDetails.hidden = true;
      return;
    }
    if (occupancyDetailsDismissed) {
      occupancyDetails.hidden = true;
      updateOccupancyDetailsToggle();
      return;
    }
    const details = entry
      ? occupancyState.spaceDetails(
        currentOccupancy,
        entry.source_space_name,
        occupancyTimeIndex,
        occupancyMetric,
        occupancyAgentClass
      )
      : occupancyState.wholeModelDetails(
        currentOccupancy, occupancyTimeIndex, occupancyAgentClass
      );
    occupancyDetails.hidden = false;
    occupancyDetailName.textContent = details.whole_model ? '整个模型' : details.source_space_name;
    occupancyConflictBadge.hidden = details.whole_model || !details.conflict;
    occupancyConflictBadge.textContent = copy('metadataConflict');
    occupancyEntranceBadge.hidden = details.whole_model || currentOccupancy.is_v3 || !details.is_flow_entrance;
    occupancyEntranceBadge.textContent = copy('entranceSeed');
    occupancyDetailCategory.textContent = details.whole_model
      ? `${details.space_count} 个 Space`
      : descriptorDisplayLabel(details.category);
    occupancyDetailPeople.textContent = `${details.current_people.toFixed(2)} people`;
    occupancyDetailDensity.textContent = `${details.density_people_m2.toFixed(4)} people/m²`;
    occupancyDetailCapacity.textContent = details.capacity_percent === null
      ? 'flow-only · no source People capacity'
      : `${details.capacity_percent.toFixed(1)}%`;
    if (details.whole_model) {
      occupancyDetailFlow.textContent = `${details.active_agent_class} · ${details.active_flow_count.toFixed(2)} 人次/15 min`;
      occupancyDetailPhase.textContent = '全模型汇总 · 受控 ABM，不是实测流量';
    } else if (currentOccupancy.is_v3) {
      const activeCount = details.agent_class_counts[occupancyAgentClass];
      occupancyDetailFlow.textContent = occupancyAgentClass === 'ALL'
        ? `${details.function} · ${details.region}`
        : `${occupancyAgentClass} · ${Number(activeCount || 0).toFixed(2)} people`;
      occupancyDetailPhase.textContent = 'directed semantic/process flow · controlled, not measured';
    } else {
      occupancyDetailFlow.textContent = details.nearest_entrance_space
        ? copy('flowRegion', {
          entrance: details.nearest_entrance_space,
          hops: details.adjacency_hops
        })
        : '—';
      occupancyDetailPhase.textContent = Number.isInteger(details.flow_phase_minutes)
        ? (details.is_flow_entrance
          ? `${details.nearest_entrance_space} · ${copy('entranceSeed')}`
          : copy('flowPhase', {minutes: details.flow_phase_minutes}))
        : '—';
    }
    occupancyDetailScenario.textContent = `${details.scenario_id} · ${details.time}`;
    occupancyDetailLoad.textContent = details.load_data_available
      ? `${details.heating_kw.toFixed(2)} / ${details.cooling_kw.toFixed(2)} kWₜₕ`
      : '未加载真实 EnergyPlus 负荷（仅展示人员）';
    const hvac = [details.public_air_loop, details.office_doas, details.zone_hvac].filter(Boolean);
    occupancyDetailHvac.textContent = details.whole_model
      ? '全模型 Zone / HVAC 汇总'
      : `${details.zone_name}${hvac.length ? ` · ${hvac.join(' / ')}` : ''}`;
    updateOccupancyDetailsToggle();
    window.requestAnimationFrame(clampOccupancyDetailsPosition);
  }

  function updateOccupancyStep(index) {
    if (!currentOccupancy || !occupancyState) return;
    occupancyTimeIndex = occupancyState.stepIndex(Number(index), 0, currentOccupancy.timestamps.length);
    occupancyTimeInput.value = String(occupancyTimeIndex);
    occupancyTimeLabel.textContent = currentOccupancy.timestamps[occupancyTimeIndex];
    occupancyTimelineCursor.setAttribute('x1', String(occupancyTimeIndex * 960 / 95));
    occupancyTimelineCursor.setAttribute('x2', String(occupancyTimeIndex * 960 / 95));
    occupancyMaximum = occupancyState.maximumMetric(
      currentOccupancy,
      occupancyTimeIndex,
      occupancyMetric,
      occupancyAgentClass
    );
    if (currentMode === 'occupancy') updateColorMode('occupancy');
    else updateLegend();
    renderOccupancyDetails();
    renderOccupancyFlowArrows();
  }

  function toggleOccupancyPlayback() {
    if (!currentOccupancy || !occupancyState) return;
    if (occupancyPlaybackTimer !== null) {
      stopOccupancyPlayback();
      return;
    }
    occupancyPlayButton.textContent = 'Ⅱ';
    occupancyPlayButton.setAttribute('aria-pressed', 'true');
    occupancyPlayButton.setAttribute('aria-label', copy('occupancyPause'));
    occupancyPlaybackTimer = window.setInterval(() => {
      updateOccupancyStep(occupancyState.stepIndex(
        occupancyTimeIndex,
        1,
        currentOccupancy.timestamps.length
      ));
    }, 420);
  }

  function scrubOccupancyTimeline(event) {
    if (!currentOccupancy || !occupancyState) return;
    const bounds = occupancyTimeInput.getBoundingClientRect();
    if (!bounds.width) return;
    const ratio = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width));
    const maximum = currentOccupancy.timestamps.length - 1;
    updateOccupancyStep(Math.round(ratio * maximum));
  }

  function reconcileOccupancyRooms() {
    if (!currentOccupancy || !roomMeshes.size) return;
    const modelRoomKeys = new Set([...roomMeshes.keys()].filter((key) => key !== 'unassigned'));
    const payloadRoomKeys = new Set(occupancySpacesByRoomKey.keys());
    const missing = [...payloadRoomKeys].filter((key) => !modelRoomKeys.has(key));
    const extra = [...modelRoomKeys].filter((key) => !payloadRoomKeys.has(key));
    if (missing.length || extra.length) {
      throw new Error(`occupancy_room_mapping_mismatch:${missing.length}:${extra.length}`);
    }
  }

  function loadOccupancyPayload(input) {
    stopOccupancyPlayback();
    occupancyDetailRoomKey = null;
    occupancyDetailsDismissed = false;
    occupancyDetailsDrag = null;
    resetOccupancyDetailsPosition();
    setOccupancyControlsMinimized(false);
    if (!input) {
      currentOccupancy = null;
      occupancySpacesByRoomKey = new Map();
      occupancyAgentClass = 'ALL';
      occupancyFlowVisible = true;
      clearGroup(occupancyFlowGroup);
      occupancyControls.hidden = true;
      occupancyClassFilters.hidden = true;
      occupancyFlowLayer.hidden = true;
      occupancyFlowEvidence.hidden = true;
      occupancyDetails.hidden = true;
      updateOccupancyDetailsToggle();
      roomFunctionOption.disabled = true;
      occupancyOption.disabled = true;
      if (['roomFunction', 'occupancy'].includes(currentMode)) updateColorMode('surfaceType');
      return;
    }
    if (!occupancyState) throw new Error('occupancy_state_kernel_unavailable');
    currentOccupancy = occupancyState.validatePayload(input);
    occupancyAgentClass = 'ALL';
    occupancyFlowVisible = true;
    occupancyFlowToggle.checked = true;
    occupancyClassButtons.forEach((button) => {
      const isActive = button.dataset.agentClass === occupancyAgentClass;
      button.classList.toggle('active', isActive);
      button.setAttribute('aria-pressed', String(isActive));
    });
    occupancySpacesByRoomKey = new Map();
    Object.values(currentOccupancy.spaces).forEach((space) => {
      const key = normalizeName(space.source_space_name);
      if (occupancySpacesByRoomKey.has(key)) throw new Error(`occupancy_room_key_duplicate:${key}`);
      occupancySpacesByRoomKey.set(key, space);
    });
    reconcileOccupancyRooms();
    roomFunctionOption.disabled = false;
    occupancyOption.disabled = false;
    occupancyControls.hidden = false;
    occupancyClassFilters.hidden = !currentOccupancy.is_v3;
    occupancyFlowLayer.hidden = !currentOccupancy.is_v3;
    occupancyFlowEvidence.hidden = !currentOccupancy.is_v3;
    occupancyScenarioLabel.textContent = `${currentOccupancy.scenario_id} · ${currentOccupancy.period_id} · 15 min`;
    occupancyTimeInput.max = String(currentOccupancy.timestamps.length - 1);
    renderOccupancyTimeline();
    updateOccupancyStep(0);
    updateColorMode('roomFunction');
    window.parent.postMessage({
      type: 'idfrepair:viewer-occupancy-ready',
      scenarioId: currentOccupancy.scenario_id,
      periodId: currentOccupancy.period_id,
      spaceCount: currentOccupancy.space_count,
      conflictCount: Number(currentOccupancy.conflict_count || 0)
    }, parentOrigin);
  }

  function applyVisibility() {
    modelMeshes.forEach((mesh) => {
      const roomEnabled = roomVisibility.get(mesh.userData.roomKey) !== false;
      const colorEnabled = !activeColorLabel || colorDescriptor(mesh.userData).label === activeColorLabel;
      const visible = roomEnabled
        && (!isolatedRoom || mesh.userData.roomKey === isolatedRoom)
        && colorEnabled;
      mesh.visible = visible;
      if (mesh.userData.edge) mesh.userData.edge.visible = visible;
    });
    highlightGroup.children.forEach((marker) => {
      marker.visible = marker.userData.mesh
        ? marker.userData.mesh.visible
        : roomVisibility.get(marker.userData.roomKey) !== false
          && (!isolatedRoom || marker.userData.roomKey === isolatedRoom);
    });
    issueOverlayGroup.children.forEach((overlay) => {
      overlay.visible = overlay.userData.mesh ? overlay.userData.mesh.visible : true;
    });
  }

  function renderRoomList() {
    roomList.replaceChildren();
    const query = normalizeName(roomSearch.value);
    const rooms = [...roomMeshes.entries()]
      .filter(([, room]) => !query || normalizeName(room.name).includes(query))
      .sort((left, right) => left[1].name.localeCompare(right[1].name));
    if (!rooms.length) {
      const message = document.createElement('p');
      message.className = 'room-empty';
      message.textContent = roomMeshes.size ? copy('noMatchingRoom') : copy('noRoomMetadata');
      roomList.append(message);
      return;
    }
    rooms.forEach(([key, room]) => {
      const row = document.createElement('div');
      row.className = `room-row${isolatedRoom === key ? ' isolated' : ''}`;
      const label = document.createElement('label');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = roomVisibility.get(key) !== false;
      checkbox.addEventListener('change', () => {
        roomVisibility.set(key, checkbox.checked);
        if (!checkbox.checked && isolatedRoom === key) isolatedRoom = null;
        applyVisibility();
        renderRoomList();
        fitMeshes();
      });
      const name = document.createElement('span');
      name.className = 'room-name';
      name.textContent = localizedValue(room.name);
      const count = document.createElement('small');
      count.textContent = String(room.meshes.length);
      name.append(count);
      label.append(checkbox, name);
      const isolate = document.createElement('button');
      isolate.type = 'button';
      isolate.className = 'room-isolate';
      isolate.textContent = isolatedRoom === key ? copy('isolated') : copy('isolate');
      isolate.addEventListener('click', () => isolateRoom(key));
      row.append(label, isolate);
      roomList.append(row);
    });
  }

  function postRoomSelection(roomKey) {
    const room = roomMeshes.get(roomKey);
    const data = room?.meshes[0]?.userData;
    if (!room || !data) return;
    const explicitStories = [...new Set(room.meshes
      .map((mesh) => mesh.userData.story)
      .filter((story) => story && !story.startsWith('Inferred level · ')))];
    const minimumZ = Math.min(...room.meshes.flatMap((mesh) => mesh.userData.vertices.map((vertex) => vertex[2])));
    const story = explicitStories.length === 1
      ? explicitStories[0]
      : (explicitStories.length > 1
        ? copy('levels', {count: explicitStories.length})
        : copy('inferredLevel', {height: minimumZ.toFixed(2)}));
    selectionState = {kind: 'room', mesh: null, roomKey};
    renderOccupancyDetails(roomKey);
    const occupancyEntry = occupancySpacesByRoomKey.get(roomKey);
    const occupancy = currentOccupancy && occupancyEntry && occupancyState
      ? occupancyState.spaceDetails(
        currentOccupancy,
        occupancyEntry.source_space_name,
        occupancyTimeIndex,
        occupancyMetric,
        occupancyAgentClass
      )
      : null;
    window.parent.postMessage({
      type: 'idfrepair:viewer-selected',
      selectionKind: 'room',
      objectName: localizedValue(room.name),
      objectType: data.space !== 'Unassigned' ? 'Space' : 'Zone',
      zone: localizedValue(data.zone),
      space: localizedValue(data.space),
      spaceType: localizedValue(data.spaceType),
      story,
      storyIsInferred: explicitStories.length === 0,
      surfaceCount: room.meshes.filter((mesh) => mesh.userData.kind === 'surface').length,
      windowCount: room.meshes.filter((mesh) => mesh.userData.kind === 'fenestration').length,
      shadingCount: room.meshes.filter((mesh) => mesh.userData.kind === 'shading').length,
      occupancy
    }, parentOrigin);
  }

  function isolateRoom(roomKey) {
    if (!roomKey || !roomMeshes.has(roomKey)) return;
    isolatedRoom = roomKey;
    roomVisibility.set(roomKey, true);
    applyVisibility();
    renderRoomList();
    fitMeshes(roomMeshes.get(roomKey).meshes);
    postRoomSelection(roomKey);
  }

  function showAllRooms() {
    isolatedRoom = null;
    roomMeshes.forEach((_room, key) => roomVisibility.set(key, true));
    applyVisibility();
    renderRoomList();
    fitMeshes();
    postFileSelection();
  }

  function hideAllRooms() {
    isolatedRoom = null;
    roomMeshes.forEach((_room, key) => roomVisibility.set(key, false));
    applyVisibility();
    renderRoomList();
    fitMeshes([]);
    postFileSelection();
  }

  function clearIsolation() {
    isolatedRoom = null;
    applyVisibility();
    renderRoomList();
    fitMeshes();
    postFileSelection();
  }

  function statusText() {
    const roomCount = [...roomMeshes.keys()].filter((key) => key !== 'unassigned').length;
    return copy('status', {
      surfaces: currentStats.building,
      windows: currentStats.fenestration,
      shades: currentStats.shading ? copy('shades', {count: currentStats.shading}) : '',
      rooms: roomCount
    });
  }

  function postFileSelection() {
    const roomCount = [...roomMeshes.keys()].filter((key) => key !== 'unassigned').length;
    const explicitStories = new Set(modelMeshes
      .map((mesh) => mesh.userData.story)
      .filter((story) => story && !story.startsWith('Inferred level · ')));
    const inferredRoomLevels = new Set([...roomMeshes.values()].map((room) => {
      const minimumZ = Math.min(...room.meshes.flatMap((mesh) => mesh.userData.vertices.map((vertex) => vertex[2])));
      return Math.round(minimumZ * 100) / 100;
    }));
    const storyCount = explicitStories.size || inferredRoomLevels.size;
    let dimensions = '';
    if (modelMeshes.length) {
      const bounds = new THREE.Box3();
      modelMeshes.forEach((mesh) => bounds.expandByObject(mesh));
      const size = bounds.getSize(new THREE.Vector3());
      dimensions = `${size.x.toFixed(2)} × ${size.y.toFixed(2)} × ${size.z.toFixed(2)} m`;
    }
    selectionState = {kind: 'file', mesh: null, roomKey: null};
    window.parent.postMessage({
      type: 'idfrepair:viewer-selected',
      selectionKind: 'file',
      objectName: currentFileName || copy('idfGeometry'),
      objectType: 'IDF',
      surfaceCount: currentStats.building,
      windowCount: currentStats.fenestration,
      shadingCount: currentStats.shading,
      roomCount,
      storyCount,
      storyCountIsInferred: explicitStories.size === 0 && inferredRoomLevels.size > 0,
      dimensions
    }, parentOrigin);
  }

  function setButtonCopy(button, key) {
    const value = copy(key);
    button.title = value;
    button.setAttribute('aria-label', value);
  }

  function updateStoryModeLabel() {
    buildingStoryOption.textContent = hasLoadedFile && !currentHasExplicitStories
      ? copy('storyFallbackMode')
      : 'BuildingStory';
  }

  function applyLocale(locale) {
    currentLocale = locale === 'en' ? 'en' : 'zh-CN';
    document.documentElement.lang = currentLocale;
    document.title = copy('title');
    viewerActions.setAttribute('aria-label', copy('controls'));
    colorModeControl.title = copy('colorMode');
    colorModeSelect.setAttribute('aria-label', copy('colorMode'));
    colorModeLabel.textContent = copy('color');
    updateStoryModeLabel();
    roomFunctionOption.textContent = copy('roomFunctionMode');
    occupancyOption.textContent = copy('occupancyMode');
    occupancyMetricSelect.setAttribute('aria-label', copy('occupancyMetric'));
    if (occupancyPlaybackTimer === null) occupancyPlayButton.setAttribute('aria-label', copy('occupancyPlay'));
    occupancyDetailsDragHandle.setAttribute('aria-label', copy('occupancyDetailsDrag'));
    occupancyDetailsDragHandle.title = copy('occupancyDetailsDrag');
    occupancyDetailsClose.setAttribute('aria-label', copy('occupancyDetailsClose'));
    occupancyDetailsClose.title = copy('occupancyDetailsClose');
    updateOccupancyDetailsToggle();
    setOccupancyControlsMinimized(occupancyControlsMinimized);
    occupancyConflictBadge.textContent = copy('metadataConflict');
    setButtonCopy(toggleRoomsButton, 'toggleRooms');
    setButtonCopy(fitButton, 'fit');
    setButtonCopy(focusButton, 'focus');
    container.setAttribute('aria-label', copy('canvas'));
    roomPanel.setAttribute('aria-label', copy('roomVisibility'));
    roomPanelTitle.textContent = copy('rooms');
    closeRoomsButton.setAttribute('aria-label', copy('closeRooms'));
    roomSearch.placeholder = copy('searchRooms');
    roomSearch.setAttribute('aria-label', copy('searchRooms'));
    showAllRoomsButton.textContent = copy('showAll');
    hideAllRoomsButton.textContent = copy('hideAll');
    clearIsolationButton.textContent = copy('clearIsolation');
    legendItems.setAttribute('aria-label', copy('colorLegend'));
    legendPreviousButton.setAttribute('aria-label', copy('previousLegend'));
    legendPreviousButton.title = copy('previousLegend');
    legendNextButton.setAttribute('aria-label', copy('nextLegend'));
    legendNextButton.title = copy('nextLegend');
    errorKeyLabel.textContent = copy('currentError');
    issueModeLegend.setAttribute('aria-label', copy('issueMode'));
    exitIssueModeButton.textContent = copy('exitIssueMode');
    exitIssueModeButton.title = copy('exitIssueMode');
    issueKeyTarget.textContent = copy('issueTarget');
    issueKeyPaired.textContent = copy('issuePaired');
    issueKeyGroup.textContent = copy('issueGroup');
    issueKeyNeutral.textContent = copy('issueNeutral');
    issueKeyBefore.textContent = copy('issueBefore');
    issueKeyAfter.textContent = copy('issueAfter');
    viewerHint.textContent = copy('hint');
    container.title = copy('hint');
    if (!currentFileName) fileLabel.textContent = copy('idfGeometry');
    if (pendingSourceKind === 'osm') {
      emptyState.querySelector('strong').textContent = copy('osmPendingTitle');
      emptyState.querySelector('small').textContent = copy('osmPendingHelp');
      statusLabel.textContent = copy('osmPendingStatus');
    } else if (hasLoadedFile && !modelMeshes.length) {
      emptyState.querySelector('strong').textContent = copy('noGeometryTitle');
      emptyState.querySelector('small').textContent = copy('noGeometryHelp');
      statusLabel.textContent = copy('noGeometryStatus');
    } else if (hasLoadedFile) {
      statusLabel.textContent = statusText();
    } else {
      emptyState.querySelector('strong').textContent = copy('emptyTitle');
      emptyState.querySelector('small').textContent = copy('emptyHelp');
      statusLabel.textContent = copy('waiting');
    }
    renderRoomList();
    updateLegend();
    if (currentIssueMode) applyIssueMode(currentIssueMode);
    else applyHighlights(currentRoots);
    if (selectionState.kind === 'surface' && selectionState.mesh) postSelection(selectionState.mesh);
    else if (selectionState.kind === 'room' && selectionState.roomKey) postRoomSelection(selectionState.roomKey);
    else if (selectionState.kind === 'file' && hasLoadedFile) postFileSelection();
  }

  function loadModel(text, name = 'IDF geometry') {
    pendingSourceKind = null;
    const parsed = parseIDFGeometry(text);
    clearGroup(modelGroup);
    clearGroup(highlightGroup);
    clearGroup(issueOverlayGroup);
    clearGroup(occupancyFlowGroup);
    modelMeshes = [];
    objectMeshes = new Map();
    roomMeshes = new Map();
    roomVisibility = new Map();
    isolatedRoom = null;
    activeColorLabel = null;
    highlightedMeshes = [];
    currentStats = parsed.stats;
    currentHasExplicitStories = parsed.hasExplicitStories;
    currentFileName = name || '';
    hasLoadedFile = true;
    updateStoryModeLabel();
    selectionState = {kind: 'none', mesh: null, roomKey: null};
    parsed.surfaces.forEach(addSurface);
    fileLabel.textContent = name;

    if (modelMeshes.length) {
      emptyState.hidden = true;
      statusLabel.textContent = statusText();
      reconcileOccupancyRooms();
      applyVisibility();
      updateColorMode(currentMode);
      renderOccupancyFlowArrows();
      renderRoomList();
      fitMeshes();
      if (currentIssueMode) applyIssueMode(currentIssueMode);
      else applyHighlights(currentRoots);
      postFileSelection();
    } else {
      emptyState.hidden = false;
      emptyState.querySelector('strong').textContent = copy('noGeometryTitle');
      emptyState.querySelector('small').textContent = copy('noGeometryHelp');
      statusLabel.textContent = copy('noGeometryStatus');
      renderRoomList();
      updateLegend();
      if (currentIssueMode) applyIssueMode(currentIssueMode);
      else applyHighlights(currentRoots);
      fitMeshes([]);
      postFileSelection();
    }
  }

  function showSourcePending(name, sourceKind) {
    loadModel('', name);
    pendingSourceKind = sourceKind === 'osm' ? 'osm' : null;
    if (!pendingSourceKind) return;
    emptyState.hidden = false;
    emptyState.querySelector('strong').textContent = copy('osmPendingTitle');
    emptyState.querySelector('small').textContent = copy('osmPendingHelp');
    statusLabel.textContent = copy('osmPendingStatus');
    window.parent.postMessage({
      type: 'idfrepair:viewer-selected',
      selectionKind: 'file',
      objectName: name,
      objectType: 'OSM',
      surfaceCount: 0,
      windowCount: 0,
      shadingCount: 0,
      roomCount: 0,
      storyCount: 0,
      storyCountIsInferred: false,
      dimensions: null
    }, parentOrigin);
  }

  function scheduleModelLoad(text, name) {
    loadRevision += 1;
    const revision = loadRevision;
    fileLabel.textContent = name || copy('idfGeometry');
    statusLabel.textContent = copy('parsing');
    window.requestAnimationFrame(() => window.setTimeout(() => {
      if (revision === loadRevision) loadModel(text, name);
    }, 0));
  }

  function resize() {
    const width = Math.max(container.clientWidth, 1);
    const height = Math.max(container.clientHeight, 1);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    clampOccupancyDetailsPosition();
  }

  function render() {
    animationFrame = window.requestAnimationFrame(render);
    renderer.render(scene, camera);
  }

  function pointerCoordinates(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    return new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1
    );
  }

  function pickMesh(event) {
    const pickableMeshes = visibleModelMeshes();
    if (!pickableMeshes.length) return null;
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(pointerCoordinates(event), camera);
    return raycaster.intersectObjects(pickableMeshes, false)[0]?.object || null;
  }

  function postSelection(mesh) {
    if (!mesh) return;
    const data = mesh.userData;
    selectionState = {kind: 'surface', mesh, roomKey: data.roomKey};
    renderOccupancyDetails(data.roomKey);
    const occupancyEntry = occupancySpacesByRoomKey.get(data.roomKey);
    const occupancy = currentOccupancy && occupancyEntry && occupancyState
      ? occupancyState.spaceDetails(
        currentOccupancy,
        occupancyEntry.source_space_name,
        occupancyTimeIndex,
        occupancyMetric,
        occupancyAgentClass
      )
      : null;
    window.parent.postMessage({
      type: 'idfrepair:viewer-selected',
      selectionKind: 'surface',
      objectName: data.name,
      objectType: data.objectType,
      surfaceType: data.surfaceType,
      construction: localizedValue(data.construction),
      boundary: localizedValue(data.boundary),
      zone: localizedValue(data.zone),
      space: localizedValue(data.space),
      spaceType: localizedValue(data.spaceType),
      story: localizedValue(data.story),
      storyIsInferred: data.storyIsInferred,
      vertexCount: data.vertexCount,
      normal: data.normal,
      occupancy
    }, parentOrigin);
  }

  function selectMesh(event) {
    const mesh = pickMesh(event);
    if (mesh) postSelection(mesh);
    else if (isolatedRoom) postRoomSelection(isolatedRoom);
    else postFileSelection();
  }

  renderer.domElement.addEventListener('pointerdown', (event) => {
    const mode = event.shiftKey ? 'pan' : 'orbit';
    drag = {x: event.clientX, y: event.clientY, moved: 0, mode};
    renderer.domElement.setPointerCapture(event.pointerId);
    container.classList.add('dragging');
    container.classList.toggle('panning', mode === 'pan');
  });
  renderer.domElement.addEventListener('pointermove', (event) => {
    if (!drag) {
      if (currentOccupancy) {
        const mesh = pickMesh(event);
        renderOccupancyDetails(mesh ? mesh.userData.roomKey : null);
      }
      return;
    }
    const deltaX = event.clientX - drag.x;
    const deltaY = event.clientY - drag.y;
    drag.moved += Math.abs(deltaX) + Math.abs(deltaY);
    drag.x = event.clientX;
    drag.y = event.clientY;
    if (drag.mode === 'pan') {
      const {right, up} = cameraBasis();
      const worldPerPixel = 2 * orbit.radius
        * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2)
        / Math.max(container.clientHeight, 1);
      orbit.target.addScaledVector(right, -deltaX * worldPerPixel);
      orbit.target.addScaledVector(up, deltaY * worldPerPixel);
    } else {
      orbit.azimuth -= deltaX * 0.008;
      orbit.elevation = THREE.MathUtils.clamp(orbit.elevation + deltaY * 0.006, 0.08, 1.42);
    }
    updateCamera();
  });
  renderer.domElement.addEventListener('pointerup', (event) => {
    if (drag && drag.moved < 5 && drag.mode !== 'pan') selectMesh(event);
    drag = null;
    container.classList.remove('dragging', 'panning');
  });
  renderer.domElement.addEventListener('pointercancel', () => {
    drag = null;
    container.classList.remove('dragging', 'panning');
  });
  renderer.domElement.addEventListener('pointerleave', () => {
    if (!drag && currentOccupancy) renderOccupancyDetails(null);
  });
  renderer.domElement.addEventListener('dblclick', (event) => {
    const mesh = pickMesh(event);
    if (!mesh) {
      clearIsolation();
      return;
    }
    postSelection(mesh);
    isolateRoom(mesh.userData.roomKey);
  });
  renderer.domElement.addEventListener('wheel', (event) => {
    event.preventDefault();
    orbit.radius = THREE.MathUtils.clamp(orbit.radius * Math.exp(event.deltaY * 0.001), 0.6, 100000);
    updateCamera();
  }, {passive: false});

  container.addEventListener('keydown', (event) => {
    if (event.key.toLowerCase() === 'r') fitMeshes();
  });
  fitButton.addEventListener('click', () => fitMeshes());
  focusButton.addEventListener('click', () => {
    const focusMeshes = issueFocusMeshes();
    if (focusMeshes.length) {
      fitMeshes(focusMeshes);
      return;
    }
    const visibleHighlights = highlightedMeshes.filter((mesh) => mesh.visible);
    fitMeshes(visibleHighlights.length ? visibleHighlights : visibleModelMeshes());
  });
  exitIssueModeButton.addEventListener('click', clearIssueMode);
  colorModeSelect.addEventListener('change', () => {
    updateColorMode(colorModeSelect.value);
    fitMeshes();
  });
  occupancyPlayButton.addEventListener('click', toggleOccupancyPlayback);
  occupancyControlsToggle.addEventListener('click', () => {
    setOccupancyControlsMinimized(!occupancyControlsMinimized);
  });
  occupancyDetailsToggle.addEventListener('click', () => {
    setOccupancyDetailsDismissed(!occupancyDetailsDismissed);
  });
  occupancyDetailsClose.addEventListener('click', () => {
    setOccupancyDetailsDismissed(true);
  });
  occupancyDetailsDragHandle.addEventListener('pointerdown', beginOccupancyDetailsDrag);
  occupancyDetailsDragHandle.addEventListener('pointermove', moveOccupancyDetails);
  occupancyDetailsDragHandle.addEventListener('pointerup', endOccupancyDetailsDrag);
  occupancyDetailsDragHandle.addEventListener('pointercancel', endOccupancyDetailsDrag);
  occupancyTimeInput.addEventListener('input', () => updateOccupancyStep(occupancyTimeInput.value));
  occupancyTimeInput.addEventListener('pointerdown', (event) => {
    occupancyTimeInput.setPointerCapture?.(event.pointerId);
    scrubOccupancyTimeline(event);
  });
  occupancyTimeInput.addEventListener('pointermove', (event) => {
    if (event.buttons || occupancyTimeInput.hasPointerCapture?.(event.pointerId)) {
      scrubOccupancyTimeline(event);
    }
  });
  occupancyMetricSelect.addEventListener('change', () => {
    occupancyMetric = occupancyState?.METRICS.includes(occupancyMetricSelect.value)
      ? occupancyMetricSelect.value
      : 'density';
    updateOccupancyStep(occupancyTimeIndex);
  });
  occupancyClassButtons.forEach((button) => {
    button.addEventListener('click', () => {
      const requestedClass = button.dataset.agentClass;
      const isKnownClass = requestedClass === 'ALL'
        || occupancyState?.V3_AGENT_CLASSES.includes(requestedClass);
      if (!currentOccupancy?.is_v3 || !isKnownClass) {
        return;
      }
      occupancyAgentClass = requestedClass;
      occupancyClassButtons.forEach((candidate) => {
        const isActive = candidate.dataset.agentClass === occupancyAgentClass;
        candidate.classList.toggle('active', isActive);
        candidate.setAttribute('aria-pressed', String(isActive));
      });
      renderOccupancyTimeline();
      updateOccupancyStep(occupancyTimeIndex);
    });
  });
  occupancyFlowToggle.addEventListener('change', () => {
    occupancyFlowVisible = occupancyFlowToggle.checked;
    renderOccupancyFlowArrows();
  });
  legendPreviousButton.addEventListener('click', () => scrollLegend(-1));
  legendNextButton.addEventListener('click', () => scrollLegend(1));
  legendItems.addEventListener('scroll', syncLegendNavigation, {passive: true});
  legendItems.addEventListener('wheel', (event) => {
    if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
    const maximumScroll = legendItems.scrollWidth - legendItems.clientWidth;
    if (maximumScroll <= 2) return;
    event.preventDefault();
    legendItems.scrollBy({left: event.deltaY, behavior: 'auto'});
  }, {passive: false});
  toggleRoomsButton.addEventListener('click', () => {
    roomPanel.hidden = !roomPanel.hidden;
    toggleRoomsButton.setAttribute('aria-expanded', String(!roomPanel.hidden));
    if (!roomPanel.hidden) roomSearch.focus();
  });
  closeRoomsButton.addEventListener('click', () => {
    roomPanel.hidden = true;
    toggleRoomsButton.setAttribute('aria-expanded', 'false');
  });
  roomSearch.addEventListener('input', renderRoomList);
  showAllRoomsButton.addEventListener('click', showAllRooms);
  hideAllRoomsButton.addEventListener('click', hideAllRooms);
  clearIsolationButton.addEventListener('click', clearIsolation);

  window.addEventListener('message', (event) => {
    if (event.source !== window.parent || event.origin !== parentOrigin) return;
    const message = event.data || {};
    try {
      if (message.type === 'idfrepair:viewer-ping') {
        window.parent.postMessage({type: 'idfrepair:viewer-ready'}, parentOrigin);
      }
      if (message.type === 'idfrepair:viewer-locale') applyLocale(message.locale);
      if (message.type === 'idfrepair:viewer-load') scheduleModelLoad(message.text, message.name);
      if (message.type === 'idfrepair:viewer-source-pending') {
        showSourcePending(message.name || 'model.osm', message.sourceKind);
      }
      if (message.type === 'idfrepair:viewer-clear') {
        loadRevision += 1;
        loadModel('', copy('idfGeometry'));
        hasLoadedFile = false;
        currentFileName = '';
        pendingSourceKind = null;
        emptyState.querySelector('strong').textContent = copy('emptyTitle');
        emptyState.querySelector('small').textContent = copy('emptyHelp');
        statusLabel.textContent = copy('waiting');
      }
      if (message.type === 'idfrepair:viewer-highlight') {
        applyHighlights(message.roots);
        const visibleHighlights = highlightedMeshes.filter((mesh) => mesh.visible);
        if (visibleHighlights.length) fitMeshes(visibleHighlights);
      }
      if (message.type === 'idfrepair:viewer-issue-mode') {
        if (message.issue) applyIssueMode(message.issue);
        else clearIssueMode();
        const focusMeshes = issueFocusMeshes();
        if (focusMeshes.length) fitMeshes(focusMeshes);
      }
      if (message.type === 'idfrepair:viewer-occupancy') {
        loadOccupancyPayload(message.payload);
      }
    } catch (_error) {
      const occupancyFailure = message.type === 'idfrepair:viewer-occupancy';
      if (!occupancyFailure) statusLabel.textContent = copy('unavailable');
      window.parent.postMessage(
        {
          type: 'idfrepair:viewer-error',
          reason: occupancyFailure ? 'occupancy_payload_invalid' : 'idf_geometry_parse_failed'
        },
        parentOrigin
      );
    }
  });

  const observer = new ResizeObserver(resize);
  if (container) observer.observe(container);
  resize();
  applyLocale('zh-CN');
  fitMeshes([]);
  render();
  window.parent.postMessage({type: 'idfrepair:viewer-ready'}, parentOrigin);

  window.addEventListener('pagehide', () => {
    stopOccupancyPlayback();
    observer.disconnect();
    window.cancelAnimationFrame(animationFrame);
    clearGroup(modelGroup);
    clearGroup(highlightGroup);
    clearGroup(issueOverlayGroup);
    clearGroup(occupancyFlowGroup);
    materialCache.forEach((material) => material.dispose());
    errorMaterial.dispose();
    markerMaterial.dispose();
    issueTargetMaterial.dispose();
    issuePairedMaterial.dispose();
    issueGroupMaterial.dispose();
    issueNeutralMaterial.dispose();
    issueTargetEdgeMaterial.dispose();
    issuePairedEdgeMaterial.dispose();
    issueGroupEdgeMaterial.dispose();
    issueNeutralEdgeMaterial.dispose();
    lineMaterial.dispose();
    renderer.dispose();
  });
})();
