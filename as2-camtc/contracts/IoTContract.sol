// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract IoTContract {
    enum SensorType { FIRE, GAS, TEMPERATURE, HUMIDITY, TRAFFIC, MOTION }
    enum AlertStatus { ACTIVE, ACKNOWLEDGED, RESOLVED }

    struct SensorRecord {
        bytes32 sensorId;
        SensorType sensorType;
        bytes32 dataHash;
        uint8 priorityTier;
        bool isAlert;
        string location;
        uint256 timestamp;
        bytes32 blockchainBlockHash;
    }

    struct Alert {
        uint256 recordId;
        AlertStatus status;
        address acknowledgedBy;
        address resolvedBy;
        uint256 acknowledgedAt;
        uint256 resolvedAt;
    }

    mapping(uint256 => SensorRecord) public sensorRecords;
    mapping(uint256 => Alert) public alerts;
    mapping(address => bool) public authorizedControllers;

    uint256 public nextRecordId;
    uint256 public totalRecords;
    uint256 public criticalAlertCount;
    uint256 public resolvedAlertCount;

    event SensorDataRecorded(uint256 indexed recordId, bytes32 sensorId, SensorType sensorType, uint8 priorityTier, uint256 timestamp);
    event CriticalAlert(uint256 indexed recordId, bytes32 sensorId, SensorType alertType, string location, uint256 timestamp);
    event AlertAcknowledged(uint256 indexed recordId, address controller);
    event AlertResolved(uint256 indexed recordId, address controller, uint256 resolutionTime);

    modifier onlyAuthorized() {
        require(authorizedControllers[msg.sender], "Not authorized");
        _;
    }

    constructor() {
        authorizedControllers[msg.sender] = true;
    }

    function authorize(address controller) external {
        require(authorizedControllers[msg.sender] || msg.sender == address(this), "Only existing auth");
        authorizedControllers[controller] = true;
    }

    function recordSensorData(
        bytes32 sensorId,
        SensorType sensorType,
        bytes32 dataHash,
        uint8 priorityTier,
        bool isAlert,
        string calldata location,
        bytes32 blockHash
    ) external onlyAuthorized returns (uint256) {
        uint256 recordId = nextRecordId++;
        sensorRecords[recordId] = SensorRecord({
            sensorId: sensorId,
            sensorType: sensorType,
            dataHash: dataHash,
            priorityTier: priorityTier,
            isAlert: isAlert,
            location: location,
            timestamp: block.timestamp,
            blockchainBlockHash: blockHash
        });
        totalRecords++;
        if (isAlert) {
            criticalAlertCount++;
            alerts[recordId] = Alert({
                recordId: recordId,
                status: AlertStatus.ACTIVE,
                acknowledgedBy: address(0),
                resolvedBy: address(0),
                acknowledgedAt: 0,
                resolvedAt: 0
            });
            emit CriticalAlert(recordId, sensorId, sensorType, location, block.timestamp);
        }
        emit SensorDataRecorded(recordId, sensorId, sensorType, priorityTier, block.timestamp);
        return recordId;
    }

    function acknowledgeAlert(uint256 alertId) external onlyAuthorized {
        Alert storage a = alerts[alertId];
        require(a.recordId != 0 || sensorRecords[alertId].timestamp != 0, "Alert not found");
        if (a.recordId == 0) a.recordId = alertId;
        a.status = AlertStatus.ACKNOWLEDGED;
        a.acknowledgedBy = msg.sender;
        a.acknowledgedAt = block.timestamp;
        emit AlertAcknowledged(alertId, msg.sender);
    }

    function resolveAlert(uint256 alertId) external onlyAuthorized {
        Alert storage a = alerts[alertId];
        require(a.recordId != 0 || sensorRecords[alertId].timestamp != 0, "Alert not found");
        if (a.recordId == 0) a.recordId = alertId;
        a.status = AlertStatus.RESOLVED;
        a.resolvedBy = msg.sender;
        a.resolvedAt = block.timestamp;
        resolvedAlertCount++;
        emit AlertResolved(alertId, msg.sender, block.timestamp);
    }

    function getStats() external view returns (uint256 total, uint256 critical, uint256 resolved) {
        total = totalRecords;
        critical = criticalAlertCount;
        resolved = resolvedAlertCount;
    }
}
