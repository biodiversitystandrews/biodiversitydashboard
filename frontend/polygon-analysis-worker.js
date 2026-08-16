/* Run stratified random-polygon comparisons away from the browser UI thread. */
importScripts('https://unpkg.com/@turf/turf@6/turf.min.js');

const GRID_SIZE = 0.001;
const RANDOM_POLYGON_BATCH_SIZE = 5;
const MAX_POINT_ATTEMPTS = 50;
const MAX_STRATUM_FAILURES = 60;
const MIN_BIODIVERSITY_RECORDS = 5;
const MIN_BIODIVERSITY_SURVEY_DAYS = 2;

let pointGrid = new Map();
let pointCount = 0;
let habitatGeoJson = null;
let habitatFeatureBboxes = [];
let habitatStrata = [];
let estateBoundary = null;
let activeRequestId = null;

self.onmessage = event => {
    const message = event.data || {};

    try {
        if (message.type === 'initialize') {
            buildPointGrid(message.points || []);
            setHabitatBoundary(message.habitatGeoJson, message.estateBoundaryGeoJson);
            self.postMessage({ type: 'ready', pointCount });
            return;
        }

        if (message.type === 'update-habitat') {
            setHabitatBoundary(message.habitatGeoJson, message.estateBoundaryGeoJson);
            self.postMessage({ type: 'habitat-ready' });
            return;
        }

        if (message.type === 'cancel') {
            activeRequestId = null;
            return;
        }

        if (message.type === 'analyse') {
            activeRequestId = message.requestId;
            analyseRandomPolygons(
                message.requestId,
                message.polygon,
                Number(message.targetCount) || 250,
                Number(message.seed) || 1,
                message.year || null
            ).catch(error => postAnalysisError(message.requestId, error));
        }
    } catch (error) {
        postAnalysisError(message.requestId, error);
    }
};

function postAnalysisError(requestId, error) {
    if (requestId !== activeRequestId) return;
    self.postMessage({
        type: 'error',
        requestId,
        message: error.message || String(error)
    });
}

function gridCoordinate(value) {
    return Math.floor(value / GRID_SIZE);
}

function gridKey(x, y) {
    return `${x}:${y}`;
}

function buildPointGrid(points) {
    pointGrid = new Map();
    pointCount = 0;

    points.forEach((point, sourceIndex) => {
        const lng = Number(point.longitude);
        const lat = Number(point.latitude);
        if (!Number.isFinite(lng) || !Number.isFinite(lat)) return;

        const compactPoint = {
            sourceIndex,
            lng,
            lat,
            species: point.species || null,
            taxa: point.taxa || null,
            obs: point.obs || null,
            year: point.year || null,
            surveyDay: normaliseSurveyDay(point.Date)
        };
        const key = gridKey(gridCoordinate(lng), gridCoordinate(lat));
        if (!pointGrid.has(key)) pointGrid.set(key, []);
        pointGrid.get(key).push(compactPoint);
        pointCount += 1;
    });
}

function normaliseSurveyDay(value) {
    if (!value) return null;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}-${String(date.getUTCDate()).padStart(2, '0')}`;
}

function setHabitatBoundary(geoJson, boundaryGeoJson) {
    habitatGeoJson = geoJson || null;
    const features = (habitatGeoJson?.features || []).filter(isPolygonFeature);
    habitatFeatureBboxes = features.map(feature => ({
        feature,
        bbox: turf.bbox(feature)
    }));
    estateBoundary = boundaryGeoJson?.features?.[0] || null;
    habitatStrata = buildHabitatStrata(features);
}

function isPolygonFeature(feature) {
    const type = feature?.geometry?.type;
    return type === 'Polygon' || type === 'MultiPolygon';
}

function buildHabitatStrata(features) {
    const groups = new Map();

    features.forEach(feature => {
        const name = String(feature.properties?.broad || 'Unknown habitat');
        const area = turf.area(feature);
        if (!Number.isFinite(area) || area <= 0) return;
        if (!groups.has(name)) groups.set(name, { name, area: 0, features: [] });
        const group = groups.get(name);
        group.area += area;
        group.features.push({ feature, area, bbox: turf.bbox(feature) });
    });

    return Array.from(groups.values()).sort((a, b) => a.name.localeCompare(b.name));
}

async function analyseRandomPolygons(requestId, polygon, targetCount, seed, year) {
    const focalPoints = getPointsInPolygon(polygon, year);
    const focalStats = calculatePolygonStatsFromPoints(focalPoints);
    const estateBounds = getRandomPlacementBounds();
    const randomStats = [];
    const comparisonFeatures = [];
    const strataCounts = {};
    const random = mulberry32(seed);
    const stratumPlan = buildStratumPlan(targetCount, random);

    if (!estateBounds || pointCount === 0) {
        postResult(requestId, focalPoints, focalStats, randomStats, comparisonFeatures, seed, strataCounts);
        return;
    }

    const centroidCoordinates = turf.centroid(polygon).geometry.coordinates;
    let attempts = 0;
    let currentStratumFailures = 0;
    const maxAttempts = targetCount * 100;

    while (
        requestId === activeRequestId &&
        randomStats.length < targetCount &&
        attempts < maxAttempts
    ) {
        for (
            let index = 0;
            index < RANDOM_POLYGON_BATCH_SIZE &&
            randomStats.length < targetCount &&
            attempts < maxAttempts;
            index += 1
        ) {
            attempts += 1;
            const plannedStratum = currentStratumFailures < MAX_STRATUM_FAILURES
                ? stratumPlan[randomStats.length]
                : null;
            const target = currentStratumFailures < MAX_STRATUM_FAILURES
                ? samplePlacementTarget(plannedStratum, estateBounds, random)
                : sampleEstateWideTarget(estateBounds, random);
            if (!target) {
                currentStratumFailures += 1;
                continue;
            }

            const orientedPolygon = turf.transformRotate(
                polygon,
                random() * 360,
                { pivot: centroidCoordinates }
            );
            const placementAnchor = randomPointWithinFeature(
                orientedPolygon,
                turf.bbox(orientedPolygon),
                random
            ) || turf.centroid(orientedPolygon).geometry.coordinates;
            const movedPolygon = translatePolygon(
                orientedPolygon,
                placementAnchor,
                target.coordinates
            );
            if (!polygonOverlapsEstate(movedPolygon)) {
                currentStratumFailures += 1;
                continue;
            }

            const acceptedStratum = target.stratum || 'Estate-wide fallback';
            const centroid = turf.centroid(movedPolygon).geometry.coordinates;
            randomStats.push({
                comparisonNumber: randomStats.length + 1,
                habitatStratum: acceptedStratum,
                centroidLongitude: centroid[0],
                centroidLatitude: centroid[1],
                ...calculatePolygonStats(movedPolygon, year)
            });
            strataCounts[acceptedStratum] = (strataCounts[acceptedStratum] || 0) + 1;
            currentStratumFailures = 0;
            comparisonFeatures.push(movedPolygon);
        }

        self.postMessage({
            type: 'progress',
            requestId,
            completed: randomStats.length,
            total: targetCount
        });
        await yieldWorker();
    }

    if (requestId === activeRequestId) {
        postResult(requestId, focalPoints, focalStats, randomStats, comparisonFeatures, seed, strataCounts);
    }
}

function buildStratumPlan(targetCount, random) {
    if (!habitatStrata.length) return Array(targetCount).fill(null);

    const plan = [];
    if (targetCount >= habitatStrata.length) {
        habitatStrata.forEach(stratum => plan.push(stratum));
    }

    const totalArea = habitatStrata.reduce((sum, stratum) => sum + stratum.area, 0);
    while (plan.length < targetCount) {
        plan.push(weightedChoice(habitatStrata, totalArea, random, item => item.area));
    }
    return shuffle(plan, random);
}

function samplePlacementTarget(stratum, estateBounds, random) {
    if (!stratum && habitatStrata.length) {
        const totalArea = habitatStrata.reduce((sum, item) => sum + item.area, 0);
        const fallbackStratum = weightedChoice(
            habitatStrata,
            totalArea,
            random,
            item => item.area
        );
        return samplePlacementTarget(fallbackStratum, estateBounds, random);
    }

    if (!stratum) {
        return {
            coordinates: [
                estateBounds.west + random() * (estateBounds.east - estateBounds.west),
                estateBounds.south + random() * (estateBounds.north - estateBounds.south)
            ],
            stratum: null
        };
    }

    const feature = weightedChoice(
        stratum.features,
        stratum.area,
        random,
        item => item.area
    );
    const coordinates = randomPointWithinFeature(feature.feature, feature.bbox, random);
    return coordinates ? { coordinates, stratum: stratum.name } : null;
}

function sampleEstateWideTarget(estateBounds, random) {
    return {
        coordinates: [
            estateBounds.west + random() * (estateBounds.east - estateBounds.west),
            estateBounds.south + random() * (estateBounds.north - estateBounds.south)
        ],
        stratum: null
    };
}

function randomPointWithinFeature(feature, bbox, random) {
    for (let attempt = 0; attempt < MAX_POINT_ATTEMPTS; attempt += 1) {
        const coordinates = [
            bbox[0] + random() * (bbox[2] - bbox[0]),
            bbox[1] + random() * (bbox[3] - bbox[1])
        ];
        if (turf.booleanPointInPolygon(turf.point(coordinates), feature)) return coordinates;
    }
    return null;
}

function weightedChoice(items, totalWeight, random, getWeight) {
    let threshold = random() * totalWeight;
    for (const item of items) {
        threshold -= getWeight(item);
        if (threshold <= 0) return item;
    }
    return items[items.length - 1];
}

function shuffle(items, random) {
    for (let index = items.length - 1; index > 0; index -= 1) {
        const swapIndex = Math.floor(random() * (index + 1));
        [items[index], items[swapIndex]] = [items[swapIndex], items[index]];
    }
    return items;
}

function translatePolygon(polygon, centroidCoordinates, targetCoordinates) {
    return turf.transformTranslate(
        polygon,
        turf.distance(centroidCoordinates, targetCoordinates, { units: 'kilometers' }),
        turf.bearing(centroidCoordinates, targetCoordinates),
        { units: 'kilometers' }
    );
}

function postResult(requestId, focalPoints, focalStats, randomStats, comparisonFeatures, seed, strataCounts) {
    const biodiversityStats = randomStats.filter(hasEnoughBiodiversityEvidence);
    self.postMessage({
        type: 'result',
        requestId,
        comparisonFeatures,
        focalStats,
        focalPointIndexes: focalPoints.map(point => point.sourceIndex),
        comparison: {
            samples: randomStats.length,
            seed,
            method: habitatStrata.length
                ? 'Habitat-stratified, area-weighted anchor placement with random orientation and estate overlap'
                : 'Estate-wide random placement with random orientation',
            strataCounts,
            results: randomStats,
            biodiversitySamples: biodiversityStats.length,
            indexPercentile: percentileFor(focalStats.biodiversityIndex, biodiversityStats, 'biodiversityIndex'),
            recordsPercentile: percentileFor(focalStats.totalRecords, randomStats, 'totalRecords'),
            speciesPercentile: percentileFor(focalStats.uniqueSpecies, biodiversityStats, 'uniqueSpecies'),
            taxaPercentile: percentileFor(focalStats.taxaGroups, biodiversityStats, 'taxaGroups'),
            surveyDaysPercentile: percentileFor(focalStats.surveyDays, randomStats, 'surveyDays'),
            observersPercentile: percentileFor(focalStats.observers, randomStats, 'observers')
        }
    });
}

function hasEnoughBiodiversityEvidence(stats) {
    return stats.totalRecords >= MIN_BIODIVERSITY_RECORDS &&
        stats.surveyDays >= MIN_BIODIVERSITY_SURVEY_DAYS;
}

function percentileFor(focalValue, values, key) {
    return calculatePercentileRank(focalValue, values.map(value => value[key]));
}

function getCandidatesFromGrid(bbox) {
    const candidates = [];
    const minX = gridCoordinate(bbox[0]);
    const maxX = gridCoordinate(bbox[2]);
    const minY = gridCoordinate(bbox[1]);
    const maxY = gridCoordinate(bbox[3]);

    for (let x = minX; x <= maxX; x += 1) {
        for (let y = minY; y <= maxY; y += 1) {
            candidates.push(...(pointGrid.get(gridKey(x, y)) || []));
        }
    }
    return candidates;
}

function getPointsInPolygon(polygon, year = null) {
    const bbox = turf.bbox(polygon);
    return getCandidatesFromGrid(bbox)
        .filter(point =>
            point.lng >= bbox[0] &&
            point.lng <= bbox[2] &&
            point.lat >= bbox[1] &&
            point.lat <= bbox[3] &&
            (!year || point.year === year)
        )
        .filter(point => turf.booleanPointInPolygon(
            turf.point([point.lng, point.lat]),
            polygon
        ));
}

function calculatePolygonStats(polygon, year = null) {
    return calculatePolygonStatsFromPoints(getPointsInPolygon(polygon, year));
}

function calculatePolygonStatsFromPoints(points) {
    const species = new Set(points.map(point => point.species).filter(Boolean));
    return {
        totalRecords: points.length,
        uniqueSpecies: species.size,
        taxaGroups: new Set(points.map(point => point.taxa).filter(Boolean)).size,
        surveyDays: new Set(points.map(point => point.surveyDay).filter(Boolean)).size,
        observers: new Set(points.map(point => point.obs).filter(Boolean)).size,
        biodiversityIndex: points.length ? species.size / points.length : null
    };
}

function getRandomPlacementBounds() {
    const placementArea = habitatGeoJson?.features?.length
        ? habitatGeoJson
        : estateBoundary;
    if (!placementArea) return null;
    const bbox = turf.bbox(placementArea);
    return { west: bbox[0], south: bbox[1], east: bbox[2], north: bbox[3] };
}

function polygonOverlapsEstate(polygon) {
    if (!habitatGeoJson?.features?.length) return false;

    if (estateBoundary) {
        try {
            return !turf.booleanDisjoint(polygon, estateBoundary);
        } catch (error) {
            // Continue to the source-feature fallback below.
        }
    }

    const polygonBbox = turf.bbox(polygon);
    return habitatFeatureBboxes.some(item => {
        if (!bboxesOverlap(polygonBbox, item.bbox)) return false;
        try {
            return !turf.booleanDisjoint(polygon, item.feature);
        } catch (error) {
            return false;
        }
    });
}

function bboxesOverlap(first, second) {
    return first[0] <= second[2] &&
        first[2] >= second[0] &&
        first[1] <= second[3] &&
        first[3] >= second[1];
}

function calculatePercentileRank(focalValue, values) {
    const usable = values.filter(Number.isFinite);
    if (!Number.isFinite(focalValue) || !usable.length) return null;
    const below = usable.filter(value => value < focalValue).length;
    const equal = usable.filter(value => value === focalValue).length;
    return ((below + 0.5 * equal) / usable.length) * 100;
}

function mulberry32(seed) {
    let value = seed >>> 0;
    return function random() {
        value += 0x6D2B79F5;
        let result = value;
        result = Math.imul(result ^ (result >>> 15), result | 1);
        result ^= result + Math.imul(result ^ (result >>> 7), result | 61);
        return ((result ^ (result >>> 14)) >>> 0) / 4294967296;
    };
}

function yieldWorker() {
    return new Promise(resolve => setTimeout(resolve, 0));
}
