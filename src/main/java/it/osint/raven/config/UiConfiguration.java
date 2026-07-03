package it.osint.raven.config;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class UiConfiguration {
    private boolean mouseEnabled;
    private String density;

    public static UiConfiguration defaults() {
        return new UiConfiguration(true, "COMFORTABLE");
    }
}
