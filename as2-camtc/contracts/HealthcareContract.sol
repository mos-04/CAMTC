// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract HealthcareContract {
    enum RecordType { CARDIAC_ALERT, MEDICATION_ORDER, VITALS_LOG, LAB_RESULT, ICU_ALERT }
    enum Priority { ROUTINE, URGENT, CRITICAL }

    struct Record {
        bytes32 patientId;
        RecordType recordType;
        bytes32 dataHash;
        uint8 priorityTier;
        uint8 priority;
        uint256 timestamp;
        address submitter;
        bool isEmergency;
        bytes32 blockchainBlockHash;
    }

    struct ResponseLog {
        uint256 alertId;
        string action;
        address responder;
        uint256 responseTime;
        uint256 alertTimestamp;
    }

    mapping(bytes32 => uint256[]) public patientRecords;
    mapping(address => bool) public authorizedProviders;
    mapping(uint256 => Record) public records;
    mapping(uint256 => ResponseLog) public responseLogs;

    uint256 public nextRecordId;
    uint256 public totalRecords;
    uint256 public emergencyCount;
    uint256 public totalResponseTime;
    uint256 public responseCount;

    event RecordAdded(uint256 indexed recordId, bytes32 indexed patientId, RecordType recordType, uint8 priorityTier, uint256 timestamp);
    event EmergencyAlert(uint256 indexed recordId, bytes32 indexed patientId, RecordType alertType, uint256 timestamp);
    event AlertResponded(uint256 indexed alertId, address responder, uint256 responseTime);

    modifier onlyAuthorized() {
        require(authorizedProviders[msg.sender], "Not authorized");
        _;
    }

    constructor() {
        authorizedProviders[msg.sender] = true;
    }

    function authorize(address provider) external {
        require(msg.sender == tx.origin || authorizedProviders[msg.sender], "Only existing auth");
        authorizedProviders[provider] = true;
    }

    function submitRecord(
        bytes32 patientId,
        RecordType recordType,
        bytes32 dataHash,
        uint8 priorityTier,
        bool isEmergency,
        bytes32 blockchainBlockHash
    ) external onlyAuthorized returns (uint256) {
        uint256 recordId = nextRecordId++;
        uint8 pri = priorityTier == 1 ? 2 : (priorityTier == 2 ? 1 : 0);
        records[recordId] = Record({
            patientId: patientId,
            recordType: recordType,
            dataHash: dataHash,
            priorityTier: priorityTier,
            priority: pri,
            timestamp: block.timestamp,
            submitter: msg.sender,
            isEmergency: isEmergency,
            blockchainBlockHash: blockchainBlockHash
        });
        patientRecords[patientId].push(recordId);
        totalRecords++;
        if (isEmergency) emergencyCount++;
        emit RecordAdded(recordId, patientId, recordType, priorityTier, block.timestamp);
        if (isEmergency) emit EmergencyAlert(recordId, patientId, recordType, block.timestamp);
        return recordId;
    }

    function respondToAlert(uint256 alertId, string calldata action, uint256 alertTimestamp) external onlyAuthorized {
        uint256 responseTime = block.timestamp - alertTimestamp;
        responseLogs[alertId] = ResponseLog({
            alertId: alertId,
            action: action,
            responder: msg.sender,
            responseTime: responseTime,
            alertTimestamp: alertTimestamp
        });
        totalResponseTime += responseTime;
        responseCount++;
        emit AlertResponded(alertId, msg.sender, responseTime);
    }

    function getRecord(uint256 id) external view returns (Record memory) {
        return records[id];
    }

    function getPatientRecords(bytes32 patientId) external view returns (uint256[] memory) {
        return patientRecords[patientId];
    }

    function getStats() external view returns (uint256 total, uint256 emergencies, uint256 avgResponse) {
        total = totalRecords;
        emergencies = emergencyCount;
        avgResponse = responseCount > 0 ? totalResponseTime / responseCount : 0;
    }
}
